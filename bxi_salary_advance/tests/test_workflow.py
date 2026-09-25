from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import SalaryAdvanceCommon


@tagged('post_install', '-at_install')
class TestSalaryAdvanceEligibility(SalaryAdvanceCommon):

    def test_limit_is_75_percent_of_monthly_gross(self):
        advance = self._new_advance().with_user(self.hr_user)
        self.assertEqual(advance.monthly_salary, 80000)
        self.assertEqual(advance.max_eligible, 60000)

    def test_limit_on_basic_salary(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_salary_advance.salary_basis', 'basic')
        advance = self._new_advance(amount=30000).with_user(self.hr_user)
        self.assertEqual(advance.monthly_salary, 40000)
        self.assertEqual(advance.max_eligible, 30000)

    def test_amount_above_limit_is_refused(self):
        advance = self._new_advance(amount=60000.01)
        with self.assertRaisesRegex(UserError, '75%'):
            advance.action_submit()
        self._new_advance(amount=60000).action_submit()

    def test_minimum_service(self):
        newcomer = self._create_employee(
            'Newcomer', parent=self.manager, joined=fields.Date.today() - relativedelta(months=5))
        for category, vals in (('emergency', {}), ('non_processing', {'nonprocessing_reason': 'other'})):
            advance = self._new_advance(category=category, amount=1000, employee=newcomer, **vals)
            with self.assertRaisesRegex(UserError, '6 months'):
                advance.action_submit()
            advance.unlink()
        # The policy sets no service minimum for housing advances.
        housing = self._new_advance(category='housing', amount=50000, employee=newcomer)
        housing.action_submit()
        self.assertEqual(housing.state, 'submitted')

    def test_category_one_only_in_india(self):
        self.company.country_id = self.env.ref('base.us')
        advance = self._new_advance(category='non_processing', amount=20000)
        with self.assertRaisesRegex(UserError, 'India'):
            advance.action_submit()

    def test_notice_period_is_not_eligible(self):
        self._resign(self.employee, self.today + timedelta(days=60))
        advance = self._new_advance()
        with self.assertRaisesRegex(UserError, 'notice period'):
            advance.action_submit()

    def test_one_outstanding_advance_at_a_time(self):
        self._new_advance(amount=10000).action_submit()
        second = self._new_advance(category='housing', amount=10000)
        with self.assertRaisesRegex(UserError, 'still open'):
            second.action_submit()

    def test_documents_required(self):
        advance = self._new_advance(request_form_ids=[(5, 0, 0)])
        with self.assertRaisesRegex(UserError, 'Advance Request Form'):
            advance.action_submit()
        housing = self._new_advance(category='housing', rental_agreement_ids=[(5, 0, 0)])
        with self.assertRaisesRegex(UserError, 'rental agreement'):
            housing.action_submit()
        self.env['ir.config_parameter'].sudo().set_param('bxi_salary_advance.request_form_optional', True)
        advance.action_submit()
        self.assertEqual(advance.state, 'submitted')

    def test_new_record_issues_for_portal(self):
        probe = self.env['bxi.salary.advance'].new({
            'employee_id': self.employee.id, 'category': 'emergency', 'emergency_type': 'birth',
            'amount_requested': 1.0,
        })
        self.assertEqual(probe._get_eligibility_issues(check_documents=False), [])


@tagged('post_install', '-at_install')
class TestSalaryAdvanceWorkflow(SalaryAdvanceCommon):

    def test_standard_approval(self):
        advance = self._new_advance()
        advance.action_submit()
        self.assertEqual(advance.state, 'submitted')
        self.assertEqual(advance.manager_id, self.manager)
        self.assertEqual(advance.lob_id, self.lob)
        self.assertTrue(advance.activity_ids.filtered(lambda a: a.user_id == self.manager.user_id))

        advance.with_user(self.manager.user_id).action_rm_approve()
        self.assertEqual(advance.state, 'hr_review')
        self.assertGreater(advance.hr_deadline, self.today)
        self.assertLessEqual(advance.hr_deadline, self.today + timedelta(days=11))

        advance.with_user(self.hr_user).action_hr_approve()
        self.assertEqual(advance.state, 'approved')
        self.assertEqual(advance.amount_approved, 45000)
        self.assertEqual(advance.installment_count, 3)
        self.assertEqual(advance.installment_amount, 15000)

    def test_only_manager_or_hr_approves(self):
        advance = self._new_advance()
        advance.action_submit()
        self.assertFalse(advance.can_rm_approve)
        with self.assertRaises(UserError):
            advance.action_rm_approve()
        with self.assertRaises(UserError):
            advance.with_user(self.finance_user).action_rm_approve()
        advance.with_user(self.manager.user_id).action_rm_approve()
        with self.assertRaises(UserError):
            advance.with_user(self.manager.user_id).action_hr_approve()

    def test_employee_cannot_change_workflow_fields(self):
        advance = self._new_advance()
        with self.assertRaises(AccessError):
            advance.write({'state': 'approved'})
        with self.assertRaises(AccessError):
            advance.write({'amount_approved': 45000})
        advance.amount_requested = 40000
        advance.action_submit()
        with self.assertRaisesRegex(UserError, 'no longer be modified'):
            advance.amount_requested = 50000

    def test_hr_can_reduce_the_amount(self):
        advance = self._new_advance()
        advance.action_submit()
        advance.with_user(self.manager.user_id).action_rm_approve()
        advance = advance.with_user(self.hr_user)
        advance.amount_approved = 30000
        advance.action_hr_approve()
        self.assertEqual(advance.amount_approved, 30000)
        self.assertEqual(advance.installment_amount, 10000)
        with self.assertRaises(ValidationError):
            advance.amount_approved = 50000

    def test_reject_with_reason(self):
        advance = self._new_advance()
        advance.action_submit()
        with self.assertRaises(UserError):
            advance.with_user(self.finance_user).action_open_reject_wizard()
        wizard = self.env['bxi.salary.advance.reject.wizard'].with_user(self.manager.user_id).create({
            'advance_id': advance.id, 'reason': 'Please apply after the appraisal cycle.'})
        wizard.action_reject()
        self.assertEqual(advance.state, 'rejected')
        self.assertEqual(advance.rejection_reason, 'Please apply after the appraisal cycle.')
        self.assertIn('appraisal cycle', advance.message_ids[0].body)
        advance.action_reset_to_draft()
        self.assertEqual(advance.state, 'draft')

    def test_cancel(self):
        advance = self._new_advance()
        advance.action_submit()
        advance.action_cancel()
        self.assertEqual(advance.state, 'cancelled')
        advance.unlink()

    def test_category_one_is_recovered_at_once(self):
        advance = self._new_advance(category='non_processing', amount=60000)
        self.assertEqual(advance.installment_count, 1)
        advance.action_submit()
        advance.with_user(self.manager.user_id).action_rm_approve()
        advance.with_user(self.hr_user).installment_count = 2
        with self.assertRaisesRegex(UserError, 'no exceptions'):
            advance.with_user(self.hr_user).action_hr_approve()

    def test_exception_goes_to_lob_hr_head(self):
        advance = self._new_advance()
        advance.action_submit()
        advance.with_user(self.manager.user_id).action_rm_approve()
        advance.with_user(self.hr_user).installment_count = 5
        advance.with_user(self.hr_user).action_hr_approve()
        self.assertEqual(advance.state, 'exception_review')
        self.assertEqual(advance.exception_approver_id, self.hr_head.user_id)
        self.assertIn('5 EMIs', advance.exception_reason)
        with self.assertRaises(UserError):
            advance.with_user(self.hr_user).action_exception_approve()
        advance.with_user(self.hr_head.user_id).action_exception_approve()
        self.assertEqual(advance.state, 'approved')
        self.assertEqual(advance.exception_approved_by_id, self.hr_head.user_id)

    def test_onsite_exception_goes_to_geo_hr_head(self):
        self.employee.onsite_offshore = 'onsite'
        advance = self._new_advance(category='housing', tenancy_months=9)
        advance.action_submit()
        advance.with_user(self.manager.user_id).action_rm_approve()
        advance.with_user(self.hr_user).vendor_partner_id = self.vendor
        with self.assertRaisesRegex(UserError, 'Geo HR Head'):
            advance.with_user(self.hr_user).action_hr_approve()
        self.company.sa_geo_hr_head_id = self.manager.user_id
        advance.with_user(self.hr_user).action_hr_approve()
        self.assertEqual(advance.state, 'exception_review')
        self.assertEqual(advance.exception_approver_id, self.manager.user_id)
        self.assertIn('9 months', advance.exception_reason)

    def test_housing_needs_vendor_and_signed_undertaking(self):
        advance = self._new_advance(category='housing', amount=90000)
        advance.action_submit()
        advance.with_user(self.manager.user_id).action_rm_approve()
        with self.assertRaisesRegex(UserError, 'third-party vendor'):
            advance.with_user(self.hr_user).action_hr_approve()
        advance.with_user(self.hr_user).vendor_partner_id = self.vendor
        advance.with_user(self.hr_user).action_hr_approve()
        self.assertEqual(advance.state, 'approved')
        self.assertEqual(advance.installment_count, 12)
        self.assertTrue(advance.sign_request_id)
        self.assertEqual(advance.sign_request_id.reference_doc, advance)
        self.assertTrue(advance._get_portal_sign_url())

        with self.assertRaisesRegex(UserError, 'undertaking'):
            self._disburse(advance, create_entry=False)
        advance.sudo()._on_undertaking_signed()
        self._disburse(advance, create_entry=False)
        self.assertEqual(advance.state, 'disbursed')
        self.assertEqual(len(advance.installment_ids), 12)
        self.assertEqual(advance.installment_ids[:1].amount, 7500)

    def test_housing_limit_needs_exception(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_salary_advance.housing_limit_percent', 100)
        advance = self._new_advance(category='housing', amount=90000)
        advance.action_submit()
        advance.with_user(self.manager.user_id).action_rm_approve()
        advance.with_user(self.hr_user).vendor_partner_id = self.vendor
        advance.with_user(self.hr_user).action_hr_approve()
        self.assertEqual(advance.state, 'exception_review')
        self.assertIn('housing limit', advance.exception_reason)

    def test_only_finance_disburses(self):
        advance = self._approve(self._new_advance())
        self.assertFalse(advance.with_user(self.hr_user).can_disburse)
        with self.assertRaises(UserError):
            advance.with_user(self.hr_user).action_open_disburse_wizard()
        self.assertTrue(advance.with_user(self.finance_user).can_disburse)

    def test_resignation_cancels_pending_advances(self):
        advance = self._approve(self._new_advance())
        self._resign(self.employee, self.today + timedelta(days=60))
        self.assertEqual(advance.state, 'cancelled')
        self.assertTrue(advance.resignation_id)

    def test_perquisite_flag(self):
        self.assertTrue(self._new_advance(amount=45000).is_perquisite)
        self.assertFalse(self._new_advance(amount=15000, employee=self.manager).is_perquisite)

    def test_manager_sees_team_requests_only(self):
        advance = self._new_advance()
        other = self._create_employee('Outsider')
        Advance = self.env['bxi.salary.advance']
        self.assertIn(advance, Advance.with_user(self.manager.user_id).search([]))
        self.assertNotIn(advance, Advance.with_user(other.user_id).search([]))
        self.assertIn(advance, Advance.with_user(self.hr_user).search([]))


@tagged('post_install', '-at_install')
class TestSalaryAdvanceCron(SalaryAdvanceCommon):

    def test_manager_reminder(self):
        advance = self._new_advance()
        advance.action_submit()
        advance.sudo().submitted_date = fields.Datetime.now() - timedelta(days=3)
        self.env['bxi.salary.advance']._cron_remind_and_escalate()
        self.assertTrue(advance.rm_reminder_sent)
        self.assertEqual(len(advance.activity_ids.filtered(lambda a: a.user_id == self.manager.user_id)), 2)

    def test_overdue_hr_processing_is_escalated(self):
        admin = self._create_employee('SA Admin').user_id
        admin.group_ids |= self.env.ref('bxi_salary_advance.group_salary_advance_admin')
        advance = self._new_advance()
        advance.action_submit()
        advance.with_user(self.manager.user_id).action_rm_approve()
        advance.sudo().hr_deadline = self.today - timedelta(days=1)
        self.assertTrue(advance.is_overdue)
        self.assertIn(advance, self.env['bxi.salary.advance'].search([('is_overdue', '=', True)]))
        self.env['bxi.salary.advance']._cron_remind_and_escalate()
        self.assertTrue(advance.sla_escalated)
        self.assertTrue(advance.activity_ids.filtered(lambda a: a.user_id == admin))
