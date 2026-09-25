# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import new_test_user, tagged
from odoo.tools import mute_logger

from ..services.client_base import HdfcUncertainError
from ..services.client_mock import MOCK_OTP, HdfcMockClient
from .common import HdfcPayrollCommon


@tagged('post_install', '-at_install')
class TestHdfcBatchFlow(HdfcPayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.emp_a = cls._create_employee('Kiran', [('50100000000021', cls.hdfc_bank, True)])
        cls.emp_b = cls._create_employee('Leela', [('30000000000022', cls.sbi_bank, True)])

    def _submitted_batch(self, net_a=45000.0, net_b=38000.0):
        slips = self._create_payslip(self.emp_a, net_a) | self._create_payslip(self.emp_b, net_b)
        batch = self._release(slips)
        batch.action_request_otp()
        batch._submit_with_otp(MOCK_OTP)
        return batch, slips

    def test_full_flow_with_accounting(self):
        slips = self._create_payslip(self.emp_a, 45000) | self._create_payslip(self.emp_b, 38000)
        batch = self._release(slips)
        self.assertEqual(batch.state, 'draft')
        self.assertEqual(batch.config_id, self.config)
        self.assertEqual(batch.amount_total, 83000)
        self.assertTrue(all(line.line_reference.startswith(batch.bank_reference) for line in batch.line_ids))

        action = batch.action_request_otp()
        self.assertEqual(action['res_model'], 'hdfc.otp.wizard')
        self.assertEqual(batch.state, 'otp_pending')

        wizard = self.env['hdfc.otp.wizard'].create({'batch_id': batch.id, 'otp': MOCK_OTP})
        wizard.action_submit()
        self.assertFalse(wizard.otp)
        self.assertEqual(batch.state, 'processing')
        self.assertTrue(batch.file_sequence_number)
        self.assertTrue(batch.file_attachment_id)
        self.assertEqual(set(batch.line_ids.mapped('state')), {'submitted'})
        self.assertEqual(set(slips.mapped('hdfc_payment_state')), {'processing'})

        self.env['hdfc.payout.batch']._cron_sync_status()
        self.assertEqual(batch.state, 'done')
        self.assertEqual(set(slips.mapped('hdfc_payment_state')), {'paid'})
        self.assertTrue(all(slips.mapped('hdfc_utr')))

        move = batch.move_ids
        self.assertEqual(len(move), 1)
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.journal_id, self.config.journal_id)
        debit_lines = move.line_ids.filtered('debit')
        self.assertEqual(debit_lines.account_id, self.config.salary_payable_account_id)
        self.assertEqual(debit_lines.partner_id, (self.emp_a | self.emp_b).work_contact_id)
        credit_line = move.line_ids.filtered('credit')
        self.assertEqual(credit_line.account_id, self.config.credit_account_id)
        self.assertEqual(credit_line.credit, 83000)

        self.assertEqual(set(batch.log_ids.mapped('operation')), {'otp', 'submit', 'status'})
        for log in batch.log_ids:
            self.assertNotIn(MOCK_OTP, log.request_masked or '')

    def test_expense_mode(self):
        self.config.salary_entry_mode = 'expense'
        batch, _slips = self._submitted_batch()
        batch._sync_status()
        self.assertEqual(batch.move_ids.line_ids.filtered('debit').account_id, self.config.salary_expense_account_id)

    def test_partial_failure(self):
        batch, slips = self._submitted_batch(net_b=38000.99)  # mock bank rejects amounts ending in .99
        batch._sync_status()
        self.assertEqual(batch.state, 'partially_done')
        slip_a, slip_b = slips
        self.assertEqual(slip_a.hdfc_payment_state, 'paid')
        self.assertEqual(slip_b.hdfc_payment_state, 'failed')
        self.assertTrue(batch.line_ids.filtered(lambda l: l.state == 'failed').failure_reason)
        self.assertEqual(batch.move_ids.line_ids.filtered('credit').credit, 45000)
        # a failed payslip can be paid again in a new batch
        self.assertTrue(slip_b.action_hdfc_release())

    def test_wrong_otp_then_lockout(self):
        batch = self._release(self._create_payslip(self.emp_a, 1000))
        batch.action_request_otp()
        self.config.otp_max_attempts = 2
        action = batch._submit_with_otp('000000')
        self.assertEqual(action['res_model'], 'hdfc.otp.wizard')
        self.assertEqual(batch.otp_attempts, 1)
        self.assertEqual(batch.state, 'otp_pending')
        batch._submit_with_otp('111111')
        self.assertEqual(batch.state, 'draft')
        self.assertFalse(batch.otp_reference)

    def test_expired_otp(self):
        batch = self._release(self._create_payslip(self.emp_a, 1000))
        batch.action_request_otp()
        batch.otp_requested_at = fields.Datetime.now() - timedelta(minutes=30)
        batch._submit_with_otp(MOCK_OTP)
        self.assertEqual(batch.state, 'draft')
        self.assertFalse(batch.file_attachment_id)

    def test_cron_expires_otp(self):
        batch = self._release(self._create_payslip(self.emp_a, 1000))
        batch.action_request_otp()
        batch.otp_requested_at = fields.Datetime.now() - timedelta(minutes=30)
        self.env['hdfc.payout.batch']._cron_expire_otp()
        self.assertEqual(batch.state, 'draft')

    def test_uncertain_submission_is_not_retried(self):
        batch = self._release(self._create_payslip(self.emp_a, 1000))
        batch.action_request_otp()
        with patch.object(HdfcMockClient, 'submit_bulk', side_effect=HdfcUncertainError('timeout')):
            batch._submit_with_otp(MOCK_OTP)
        self.assertEqual(batch.state, 'processing')
        self.assertFalse(batch.file_sequence_number)
        failed_log = batch.log_ids.filtered(lambda log: log.operation == 'submit')
        self.assertFalse(failed_log.success)
        batch._sync_status()
        self.assertEqual(batch.state, 'done')

    def test_reverse_creates_counter_entry(self):
        batch, slips = self._submitted_batch()
        batch._sync_status()
        payment_move = batch.move_ids
        wizard = self.env['hdfc.reverse.wizard'].create({'batch_id': batch.id, 'reason': 'Wrong month'})
        wizard.action_reverse()
        self.assertEqual(batch.state, 'reversed')
        self.assertEqual(set(batch.line_ids.mapped('state')), {'reversed'})
        self.assertEqual(set(slips.mapped('hdfc_payment_state')), {'reversed'})
        reversal = batch.move_ids - payment_move
        self.assertEqual(len(reversal), 1)
        self.assertEqual(reversal.line_ids.filtered('debit').account_id, self.config.credit_account_id)
        self.assertEqual(sum(reversal.line_ids.mapped('credit')), 83000)

    def test_returned_line_after_payment(self):
        batch, _slips = self._submitted_batch()
        batch._sync_status()
        line_b = batch.line_ids.filtered(lambda l: l.employee_id == self.emp_b)
        returned = [{'line_reference': line_b.line_reference, 'status': 'returned', 'reason': 'Account frozen'}]
        with patch.object(HdfcMockClient, 'get_status', return_value=returned):
            batch.action_refresh_status()
        self.assertEqual(line_b.state, 'returned')
        self.assertTrue(line_b.reversal_move_id)
        self.assertEqual(line_b.reversal_move_id.line_ids.filtered('credit').credit, 38000)
        self.assertEqual(batch.state, 'partially_done')

    def test_cancel_and_delete(self):
        slip = self._create_payslip(self.emp_a, 1000)
        batch = self._release(slip)
        batch.action_cancel()
        self.assertEqual(batch.state, 'cancelled')
        self.assertEqual(slip.hdfc_payment_state, 'not_paid')
        batch.unlink()
        batch2, _slips = self._submitted_batch()
        with self.assertRaises(UserError):
            batch2.unlink()

    @mute_logger('odoo.sql_db')
    def test_duplicate_line_blocked_in_database(self):
        slip = self._create_payslip(self.emp_a, 1000)
        batch = self._release(slip)
        line = batch.line_ids
        with self.assertRaises(Exception), self.cr.savepoint():
            line.copy({'batch_id': batch.id, 'line_reference': 'DUP0001'})
            self.env.flush_all()

    def test_only_manager_can_approve(self):
        user = new_test_user(
            self.env, login='hdfc_user', groups='bxi_hdfc_payroll.group_hdfc_payout_user',
            company_id=self.company.id, company_ids=self.company.ids,
        )
        batch = self._release(self._create_payslip(self.emp_a, 1000))
        with self.assertRaises(AccessError):
            batch.with_user(user).action_request_otp()
