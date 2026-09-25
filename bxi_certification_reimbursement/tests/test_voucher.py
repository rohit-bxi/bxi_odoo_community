from datetime import timedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import CertificationCommon


@tagged('post_install', '-at_install')
class TestCertificationVoucher(CertificationCommon):

    def _voucher(self, cost=5000, deadline_in=30, **vals):
        values = {
            'employee_id': self.engineer.id,
            'certification_id': self.certification.id,
            'cost': cost,
            'voucher_code': 'CODE-1',
            'issue_date': self.today - timedelta(days=5),
            'deadline': self.today + timedelta(days=deadline_in),
        }
        values.update(vals)
        return self.env['bxi.certification.voucher'].create(values)

    def _complete(self, voucher):
        voucher.write({'exam_clear_date': self.today, 'certificate_attachment_ids': [(6, 0, self.pdf.ids)]})
        voucher.action_mark_used()

    def test_issue(self):
        voucher = self._voucher()
        self.assertTrue(voucher.name.startswith('CERT-VOU/'))
        voucher.action_issue()
        self.assertEqual(voucher.state, 'issued')
        self.assertTrue(voucher.message_ids.filtered(lambda m: self.engineer.work_contact_id in m.partner_ids))
        with self.assertRaises(UserError):
            voucher.action_issue()

    def test_deadline_before_issue_date(self):
        voucher = self._voucher(deadline_in=-10)
        with self.assertRaises(UserError):
            voucher.action_issue()

    def test_mark_used_requires_proof(self):
        voucher = self._voucher()
        voucher.action_issue()
        with self.assertRaises(UserError):
            voucher.action_mark_used()
        with self.assertRaises(UserError):
            self._voucher().action_mark_used()  # not issued

    def test_used_below_threshold_has_no_agreement(self):
        voucher = self._voucher(cost=5000)
        voucher.action_issue()
        self._complete(voucher)
        self.assertEqual(voucher.state, 'used')
        self.assertFalse(voucher.service_agreement_id)

    def test_used_from_threshold_creates_agreement(self):
        voucher = self._voucher(cost=25000)
        voucher.action_issue()
        self._complete(voucher)
        agreement = voucher.service_agreement_id
        self.assertEqual(agreement.period_months, 12)
        self.assertEqual(agreement.amount, 25000)
        self.assertEqual(agreement.start_date, self.today)
        self.assertEqual(agreement.voucher_id, voucher)
        self.assertEqual(agreement.certification_label, self.certification.display_name)

    def test_employee_completes_own_voucher(self):
        voucher = self._voucher()
        voucher.action_issue()
        own = voucher.with_user(self.engineer.user_id)
        upload = self.env['ir.attachment'].with_user(self.engineer.user_id).create({
            'name': 'my-certificate.pdf', 'raw': b'%PDF-1.4',
        })
        own.write({'exam_clear_date': self.today, 'certificate_attachment_ids': [(6, 0, upload.ids)]})
        own.action_mark_used()
        self.assertEqual(voucher.state, 'used')

    def test_employee_cannot_change_voucher_details(self):
        voucher = self._voucher().with_user(self.engineer.user_id)
        with self.assertRaises(AccessError):
            voucher.write({'cost': 1})
        with self.assertRaises(AccessError):
            voucher.write({'state': 'used'})

    def test_voucher_code_hidden_from_employee(self):
        voucher = self._voucher().with_user(self.engineer.user_id)
        with self.assertRaises(AccessError):
            voucher.read(['voucher_code'])

    def test_employee_sees_only_own_vouchers(self):
        own = self._voucher()
        other = self._voucher(employee_id=self.manager.id)
        Voucher = self.env['bxi.certification.voucher'].with_user(self.engineer.user_id)
        self.assertEqual(Voucher.search([('id', 'in', (own | other).ids)]), own)

    def test_deadline_cron(self):
        expired = self._voucher(deadline_in=-1, issue_date=self.today - timedelta(days=30))
        running = self._voucher(deadline_in=20)
        reminded = self._voucher(deadline_in=7)
        (expired | running | reminded).action_issue()
        self.env['bxi.certification.voucher']._cron_check_deadlines()
        self.assertEqual(expired.state, 'expired')
        self.assertTrue(expired.activity_ids)
        self.assertEqual(running.state, 'issued')
        self.assertEqual(reminded.state, 'issued')
        self.assertTrue(reminded.message_ids.filtered(lambda m: 'Reminder' in m.body))
        self.assertFalse(running.message_ids.filtered(lambda m: 'Reminder' in m.body))

    def test_expired_voucher_recovery(self):
        voucher = self._voucher(state='expired')
        voucher.action_mark_recovered()
        self.assertEqual(voucher.state, 'recovered')
        voucher = self._voucher(state='expired')
        voucher.action_waive()
        self.assertEqual(voucher.state, 'waived')
        issued = self._voucher(state='issued')
        issued.action_mark_recovered()
        self.assertEqual(issued.state, 'issued', "Only expired vouchers are recovered")

    def test_completed_after_expiry(self):
        voucher = self._voucher(state='expired')
        self._complete(voucher)
        self.assertEqual(voucher.state, 'used')

    def test_cancel(self):
        voucher = self._voucher()
        voucher.action_cancel()
        self.assertEqual(voucher.state, 'cancelled')
        with self.assertRaises(UserError):
            self._voucher(state='used').action_cancel()
