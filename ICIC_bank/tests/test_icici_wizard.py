# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .common import ICICICommon


@tagged('post_install', '-at_install')
class TestICICIOtpWizard(ICICICommon):

    def setUp(self):
        super().setUp()
        self.employee = self._create_employee_with_bank(
            "Ajinkya Gaikwad", "123456789012", "ICIC0006939",
        )
        self.slip = self._create_payslip(self.employee)
        self.slip.write({
            'icici_payment_status': 'otp_pending',
            'icici_reference': 'REF123456789',
        })

    def _make_wizard(self, **vals):
        return self.env['icici.otp.wizard'].create({
            'otp': '998877',
            'payslip_ids': [(6, 0, self.slip.ids)],
            'payment_date': '2026-01-15',
            **vals,
        })

    def test_blank_otp_raises(self):
        wizard = self._make_wizard(otp='   ')
        with self.assertRaises(ValidationError):
            wizard.action_confirm_otp()

    def test_payslip_not_awaiting_otp_raises(self):
        self.slip.icici_payment_status = 'draft'
        wizard = self._make_wizard()
        with self.assertRaises(ValidationError):
            wizard.action_confirm_otp()

    def test_missing_reference_raises(self):
        self.slip.icici_reference = False
        wizard = self._make_wizard()
        with self.assertRaises(ValidationError):
            wizard.action_confirm_otp()

    def test_success_delegates_to_process_bulk_payment(self):
        wizard = self._make_wizard()
        with patch.object(
            type(self.slip), 'process_bulk_payment', return_value=True,
        ) as mock_process:
            result = wizard.action_confirm_otp()

        mock_process.assert_called_once_with('998877', wizard.payment_date)
        self.assertEqual(
            result, {'type': 'ir.actions.client', 'tag': 'reload'})

    def test_unexpected_error_wrapped_in_validation_error(self):
        wizard = self._make_wizard()
        with patch.object(
            type(self.slip), 'process_bulk_payment',
            side_effect=RuntimeError('boom'),
        ):
            with self.assertRaises(ValidationError):
                wizard.action_confirm_otp()

    def test_validation_error_propagates_unchanged(self):
        wizard = self._make_wizard()
        with patch.object(
            type(self.slip), 'process_bulk_payment',
            side_effect=ValidationError('Bank rejected the OTP.'),
        ):
            with self.assertRaises(ValidationError) as capture:
                wizard.action_confirm_otp()
        self.assertIn('Bank rejected the OTP.', str(capture.exception))


@tagged('post_install', '-at_install')
class TestICICIReverseWizard(ICICICommon):

    def setUp(self):
        super().setUp()
        self.employee = self._create_employee_with_bank(
            "Aaron Pereira", "123456789012", "ICIC0006939",
        )
        self.slip = self._create_payslip(self.employee)
        self.slip.write({
            'icici_payment_status': 'processing',
            'icici_reference': 'REF123456789',
            'icici_file_seq_num': '7958579',
        })

    def _make_wizard(self, **vals):
        return self.env['icici.reverse.wizard'].create({
            'payslip_id': self.slip.id,
            'file_seq_num': '7958579',
            **vals,
        })

    def test_wrong_status_raises(self):
        self.slip.icici_payment_status = 'paid'
        wizard = self._make_wizard()
        with self.assertRaises(ValidationError):
            wizard.action_reverse()

    def test_success_delegates_to_action_reverse_payment(self):
        wizard = self._make_wizard()
        with patch.object(
            type(self.slip), 'action_reverse_payment', return_value=True,
        ) as mock_reverse:
            result = wizard.action_reverse()

        mock_reverse.assert_called_once_with('7958579')
        self.assertEqual(
            result, {'type': 'ir.actions.client', 'tag': 'reload'})

    def test_unexpected_error_wrapped_in_validation_error(self):
        wizard = self._make_wizard()
        with patch.object(
            type(self.slip), 'action_reverse_payment',
            side_effect=RuntimeError('boom'),
        ):
            with self.assertRaises(ValidationError):
                wizard.action_reverse()
