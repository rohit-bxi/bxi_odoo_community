from datetime import timedelta
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CertificationCommon


@tagged('post_install', '-at_install')
class TestCertificationInclusion(CertificationCommon):

    def _inclusion(self, user=None, **vals):
        values = {
            'employee_id': self.engineer.id,
            'lob_id': self.lob.id,
            'certification_name': 'Terraform Associate',
            'version_exam_no': '003',
            'certifying_body': 'HashiCorp',
            'area': 'Infrastructure',
            'cost': 70,
            'currency_id': self.env.ref('base.USD').id,
            'website': 'https://www.hashicorp.com',
            'information': 'Infrastructure as code',
            'business_case': 'Client projects use Terraform',
        }
        values.update(vals)
        return self.env['bxi.certification.inclusion'].with_user(user or self.engineer.user_id).create(values)

    def test_submit_sets_working_day_deadline(self):
        # Standard Monday-Friday calendar, whatever the company's calendar is.
        self.engineer.resource_calendar_id = self.env['resource.calendar'].create({'name': 'Test 40h'})
        inclusion = self._inclusion()
        self.assertTrue(inclusion.name.startswith('CERT-INC/'))
        inclusion.action_submit()
        self.assertEqual(inclusion.state, 'submitted')
        self.assertEqual(inclusion.submit_date, self.today)
        # 10 working days always span at least one full weekend and never end on one.
        self.assertGreaterEqual((inclusion.deadline_date - self.today).days, 11)
        self.assertLess(inclusion.deadline_date.weekday(), 5)
        self.assertTrue(inclusion.sudo().activity_ids.filtered(lambda a: a.user_id == self.academy_head.user_id))
        with self.assertRaises(UserError):
            inclusion.action_submit()

    def test_deadline_when_calendar_gives_no_date(self):
        # Falls back to calendar days when the working calendar cannot plan the deadline.
        inclusion = self._inclusion()
        Calendar = type(self.env['resource.calendar'])
        with patch.object(Calendar, 'plan_days', lambda *args, **kwargs: False):
            self.assertEqual(inclusion.sudo()._get_deadline(), self.today + timedelta(days=10))

    def test_academy_includes_certification(self):
        inclusion = self._inclusion()
        inclusion.action_submit()
        with self.assertRaises(UserError):
            inclusion.action_approve()  # the employee is not the academy
        inclusion.with_user(self.academy_head.user_id).action_approve()
        certification = inclusion.certification_id
        self.assertEqual(inclusion.state, 'approved')
        self.assertEqual(certification.name, 'Terraform Associate')
        self.assertEqual(certification.version_exam_no, '003')
        self.assertEqual(certification.lob_id, self.lob)
        self.assertEqual(certification.currency_id, self.env.ref('base.USD'))
        self.assertFalse(inclusion.sudo().activity_ids)
        self.assertTrue(inclusion.sudo().message_ids.filtered(
            lambda m: self.engineer.work_contact_id in m.partner_ids and 'Terraform' in m.body))

    def test_academy_rejects_with_response(self):
        inclusion = self._inclusion()
        inclusion.action_submit()
        academy = inclusion.with_user(self.academy_head.user_id)
        with self.assertRaises(UserError):
            academy.action_reject()  # response missing
        academy.response = 'Not relevant for our projects'
        academy.action_reject()
        self.assertEqual(inclusion.state, 'rejected')
        self.assertFalse(inclusion.certification_id)
        inclusion.action_reset_to_draft()
        self.assertEqual(inclusion.state, 'draft')

    def test_academy_of_another_lob_cannot_decide(self):
        other_head = self._create_employee('Other Academy', '3.1', self.band4)
        other_head.user_id.group_ids |= self.env.ref('bxi_certification_reimbursement.group_certification_academy')
        self.env['bxi.line.of.business'].create({
            'name': 'Other', 'code': 'TEST-OTH', 'academy_head_id': other_head.id,
        })
        inclusion = self._inclusion()
        inclusion.action_submit()
        with self.assertRaises(UserError):
            inclusion.with_user(other_head.user_id).action_approve()

    def test_employee_sees_only_own_requests(self):
        own = self._inclusion()
        other = self._inclusion(user=self.env.ref('base.user_root'), employee_id=self.manager.id)
        Inclusion = self.env['bxi.certification.inclusion'].with_user(self.engineer.user_id)
        self.assertEqual(Inclusion.search([('id', 'in', (own | other).ids)]), own)

    def test_overdue_cron(self):
        inclusion = self._inclusion().sudo()
        inclusion.action_submit()
        inclusion.deadline_date = self.today - timedelta(days=1)
        self.env['bxi.certification.inclusion']._cron_remind_overdue()
        self.assertTrue(inclusion.message_ids.filtered(lambda m: 'past its response date' in m.body))
