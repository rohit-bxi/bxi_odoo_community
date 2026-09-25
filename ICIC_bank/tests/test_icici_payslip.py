# -*- coding: utf-8 -*-
import json
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .common import ICICICommon


def _api_result(payload):
    """Build the dict shape ``call_icici_api`` returns on success."""
    return {"status_code": 200, "response": json.dumps(payload)}


@tagged('post_install', '-at_install')
class TestActionReleaseSalary(ICICICommon):

    def setUp(self):
        super().setUp()
        self.employee = self._create_employee_with_bank(
            "Ajinkya Gaikwad", "123456789012", "ICIC0006939",
        )
        self.slip = self._create_payslip(self.employee)

    def test_no_payslips_selected_raises(self):
        with self.assertRaises(ValidationError):
            self.env['hr.payslip'].action_release_salary()

    def test_already_in_progress_raises(self):
        self.slip.icici_payment_status = 'processing'
        with self.assertRaises(ValidationError):
            self.slip.action_release_salary()

    def test_unconfirmed_state_raises(self):
        self.slip.state = 'draft'
        with self.assertRaises(ValidationError):
            self.slip.action_release_salary()

    def test_missing_bank_account_raises(self):
        employee = self.env['hr.employee'].create({'name': 'No Bank Employee'})
        slip = self._create_payslip(employee)
        with self.assertRaises(ValidationError):
            slip.action_release_salary()

    def test_invalid_amount_raises(self):
        self.slip.write({'net_wage': 0.0})
        with self.assertRaises(ValidationError):
            self.slip.action_release_salary()

    def test_success_sets_otp_pending_and_reference(self):
        with patch.object(
            type(self.slip), 'call_icici_api',
            return_value=_api_result({"RESPONSE": "SUCCESS", "OTP": "998877"}),
        ) as mock_call:
            action = self.slip.action_release_salary()

        self.assertEqual(self.slip.icici_payment_status, 'otp_pending')
        self.assertTrue(self.slip.icici_reference)
        self.assertEqual(self.slip.icici_generated_otp, '998877')
        self.assertEqual(action['res_model'], 'icici.otp.wizard')
        mock_call.assert_called_once()
        called_url = mock_call.call_args.args[0]
        self.assertIn('/Create', called_url)

    def test_sandbox_base_url_uses_sandbox_endpoint_and_ids(self):
        self.slip.company_id.icici_base_url = (
            "https://apibankingonesandbox.icici.bank.in")
        self.slip.company_id.write({
            'icici_aggr_id': False,
            'icici_aggr_name': False,
            'icici_urn': False,
        })
        with patch.object(
            type(self.slip), 'call_icici_api',
            return_value=_api_result({"RESPONSE": "SUCCESS"}),
        ) as mock_call:
            self.slip.action_release_salary()

        called_url, payload = mock_call.call_args.args
        self.assertEqual(
            called_url,
            "https://apibankingonesandbox.icici.bank.in"
            "/api/Corporate/CIB_SV/v1/Create",
        )
        self.assertEqual(payload["AGGRID"], "CIBBULK001")
        self.assertEqual(payload["URN"], "CIBTESTING")

    def test_otp_pending_can_request_new_otp(self):
        self.slip.write({
            'icici_payment_status': 'otp_pending',
            'icici_reference': 'OLDREFERENCE0001',
        })
        with patch.object(
            type(self.slip), 'call_icici_api',
            return_value=_api_result({"RESPONSE": "SUCCESS", "OTP": "123456"}),
        ):
            self.slip.action_release_salary()

        self.assertEqual(self.slip.icici_payment_status, 'otp_pending')
        self.assertNotEqual(self.slip.icici_reference, 'OLDREFERENCE0001')
        self.assertEqual(self.slip.icici_generated_otp, '123456')

    def test_create_api_failure_raises(self):
        with patch.object(
            type(self.slip), 'call_icici_api',
            return_value=_api_result(
                {"RESPONSE": "FAILED", "MESSAGE": "Corp ID invalid"}),
        ):
            with self.assertRaises(ValidationError) as capture:
                self.slip.action_release_salary()
        self.assertIn("Corp ID invalid", str(capture.exception))

    def test_empty_api_response_raises(self):
        with patch.object(
            type(self.slip), 'call_icici_api',
            return_value={"status_code": 200, "response": ""},
        ):
            with self.assertRaises(ValidationError):
                self.slip.action_release_salary()


@tagged('post_install', '-at_install')
class TestGenerateSalaryFile(ICICICommon):

    def test_no_valid_payslips_raises(self):
        with self.assertRaises(ValidationError):
            self.env['hr.payslip'].generate_salary_file('2026-01-01')

    def test_missing_bank_account_raises(self):
        employee = self.env['hr.employee'].create({'name': 'No Bank Employee'})
        slip = self._create_payslip(employee)
        with self.assertRaises(ValidationError):
            slip.generate_salary_file('2026-01-01')

    def test_short_account_number_raises(self):
        employee = self._create_employee_with_bank(
            "Short Acc", "1234", "ICIC0006939")
        slip = self._create_payslip(employee)
        with self.assertRaises(ValidationError):
            slip.generate_salary_file('2026-01-01')

    def test_invalid_ifsc_length_raises(self):
        employee = self._create_employee_with_bank(
            "Bad IFSC", "123456789012", "ICIC069",
        )
        slip = self._create_payslip(employee)
        with self.assertRaises(ValidationError):
            slip.generate_salary_file('2026-01-01')

    def test_invalid_amount_raises(self):
        employee = self._create_employee_with_bank(
            "Zero Wage", "123456789012", "ICIC0006939",
        )
        slip = self._create_payslip(employee, net_wage=0.0)
        with self.assertRaises(ValidationError):
            slip.generate_salary_file('2026-01-01')

    def test_icici_account_uses_mcw_wib(self):
        employee = self._create_employee_with_bank(
            "Ajinkya Gaikwad", "123456789012", "ICIC0006939",
        )
        slip = self._create_payslip(employee, net_wage=45000.5)

        salary_file = slip.generate_salary_file('2026-01-15')
        lines = salary_file.split('\r\n')

        self.assertTrue(lines[0].startswith('FHR|2|'))
        self.assertTrue(lines[1].startswith('MDR|'))
        detail = lines[2]
        self.assertTrue(detail.startswith('MCW|123456789012|0011|'))
        self.assertIn('45000.50', detail)
        self.assertIn('WIB', detail)
        self.assertTrue(detail.endswith('|ICIC0000011^'))
        self.assertIn('|ICIC0000011|WIB^', lines[1])

    def test_non_icici_account_uses_mco_nft(self):
        employee = self._create_employee_with_bank(
            "Ritika Shekhawat", "987654321098", "HDFC0001234",
        )
        slip = self._create_payslip(employee, net_wage=30000.0)

        salary_file = slip.generate_salary_file('2026-01-15')
        detail = salary_file.split('\r\n')[2]

        self.assertTrue(detail.startswith('MCO|987654321098|0011|'))
        self.assertIn('NFT', detail)

    def test_multiple_payslips_sum_total_amount(self):
        employee1 = self._create_employee_with_bank(
            "Emp One", "111111111111", "ICIC0006939")
        employee2 = self._create_employee_with_bank(
            "Emp Two", "222222222222", "ICIC0006939")
        slip1 = self._create_payslip(employee1, net_wage=10000.0)
        slip2 = self._create_payslip(employee2, net_wage=20000.0)

        salary_file = (slip1 + slip2).generate_salary_file('2026-01-15')
        header = salary_file.split('\r\n')[0]

        self.assertTrue(header.startswith('FHR|3|'))
        self.assertIn('30000.00', header)


@tagged('post_install', '-at_install')
class TestProcessBulkPayment(ICICICommon):

    def setUp(self):
        super().setUp()
        self.employee = self._create_employee_with_bank(
            "Aaron Pereira", "123456789012", "ICIC0006939",
        )
        self.slip = self._create_payslip(self.employee)
        self.slip.write({
            'icici_payment_status': 'otp_pending',
            'icici_reference': 'REF123456789',
        })

    def test_no_payslips_selected_raises(self):
        with self.assertRaises(ValidationError):
            self.env['hr.payslip'].process_bulk_payment('123456', '2026-01-01')

    def test_blank_otp_raises(self):
        with self.assertRaises(ValidationError):
            self.slip.process_bulk_payment('  ', '2026-01-01')

    def test_wrong_status_raises(self):
        self.slip.icici_payment_status = 'draft'
        with self.assertRaises(ValidationError):
            self.slip.process_bulk_payment('123456', '2026-01-01')

    def test_missing_reference_raises(self):
        self.slip.icici_reference = False
        with self.assertRaises(ValidationError):
            self.slip.process_bulk_payment('123456', '2026-01-01')

    def test_success_updates_processing_state(self):
        with patch.object(
            type(self.slip), 'call_icici_api',
            return_value=_api_result({
                "RESPONSE": "SUCCESS",
                "FILE_SEQUENCE_NUM": "7958579",
                "UTR": "UTR0001",
            }),
        ):
            result = self.slip.process_bulk_payment('123456', '2026-01-01')

        self.assertTrue(result)
        self.assertEqual(self.slip.icici_payment_status, 'processing')
        self.assertEqual(self.slip.icici_file_seq_num, '7958579')
        self.assertEqual(self.slip.icici_utr, 'UTR0001')
        self.assertFalse(self.slip.icici_generated_otp)

    def test_file_name_has_no_underscore(self):
        """ICICI answers 8017 "Invalid Request" for names containing "_"."""
        with patch.object(
            type(self.slip), 'call_icici_api',
            return_value=_api_result({"RESPONSE": "SUCCESS"}),
        ) as mock_call:
            self.slip.process_bulk_payment('123456', '2026-01-01')

        file_name = mock_call.call_args.args[1]["FILE_NAME"]
        self.assertRegex(file_name, r"^[A-Za-z0-9]+\.txt$")

    def test_file_sequence_parsed_from_message_when_missing(self):
        with patch.object(
            type(self.slip), 'call_icici_api',
            return_value=_api_result({
                "MESSAGE_DESC": (
                    "Processed successfully. "
                    "File Sequence No : [8123456]"
                ),
            }),
        ):
            self.slip.process_bulk_payment('123456', '2026-01-01')

        self.assertEqual(self.slip.icici_file_seq_num, '8123456')

    def test_failure_response_raises(self):
        with patch.object(
            type(self.slip), 'call_icici_api',
            return_value=_api_result(
                {"RESPONSE": "FAILED", "MESSAGE": "Invalid OTP"}),
        ):
            with self.assertRaises(ValidationError) as capture:
                self.slip.process_bulk_payment('123456', '2026-01-01')
        self.assertIn("Invalid OTP", str(capture.exception))


@tagged('post_install', '-at_install')
class TestActionReversePayment(ICICICommon):

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

    def test_missing_file_seq_num_raises(self):
        with self.assertRaises(ValidationError):
            self.slip.action_reverse_payment(False)

    def test_missing_reference_raises(self):
        self.slip.icici_reference = False
        with self.assertRaises(ValidationError):
            self.slip.action_reverse_payment('7958579')

    def test_wrong_status_raises(self):
        self.slip.icici_payment_status = 'paid'
        with self.assertRaises(ValidationError):
            self.slip.action_reverse_payment('7958579')

    def test_success_marks_reversed(self):
        with patch.object(
            type(self.slip), 'call_icici_api',
            return_value=_api_result({"RESPONSE": "SUCCESS"}),
        ):
            result = self.slip.action_reverse_payment('7958579')

        self.assertTrue(result)
        self.assertEqual(self.slip.icici_payment_status, 'reversed')
        self.assertFalse(self.slip.icici_file_seq_num)
        self.assertFalse(self.slip.icici_utr)

    def test_user_id_is_qualified_with_corp_id(self):
        self.slip.company_id.write({
            'icici_corp_id': 'TXBCORP2',
            'icici_user_id': 'USER2',
        })
        with patch.object(
            type(self.slip), 'call_icici_api',
            return_value=_api_result({"RESPONSE": "SUCCESS"}),
        ) as mock_call:
            self.slip.action_reverse_payment('7958579')

        payload = mock_call.call_args.args[1]
        self.assertEqual(payload["USERID"], "TXBCORP2.USER2")

    def test_xml_wrapped_response_is_unwrapped(self):
        with patch.object(
            type(self.slip), 'call_icici_api',
            return_value=_api_result({"XML": {"RESPONSE": "SUCCESS"}}),
        ):
            self.slip.action_reverse_payment('7958579')

        self.assertEqual(self.slip.icici_payment_status, 'reversed')

    def test_failure_response_raises(self):
        with patch.object(
            type(self.slip), 'call_icici_api',
            return_value=_api_result(
                {"RESPONSE": "FAILED", "MESSAGE": "Already settled"}),
        ):
            with self.assertRaises(ValidationError) as capture:
                self.slip.action_reverse_payment('7958579')
        self.assertIn("Already settled", str(capture.exception))


@tagged('post_install', '-at_install')
class TestActionOpenReverseWizard(ICICICommon):

    def setUp(self):
        super().setUp()
        self.employee = self._create_employee_with_bank(
            "Aaron Pereira", "123456789012", "ICIC0006939",
        )
        self.slip = self._create_payslip(self.employee)

    def test_wrong_status_raises(self):
        self.slip.icici_payment_status = 'draft'
        with self.assertRaises(ValidationError):
            self.slip.action_open_reverse_wizard()

    def test_missing_file_seq_num_raises(self):
        self.slip.icici_payment_status = 'processing'
        self.slip.icici_file_seq_num = False
        with self.assertRaises(ValidationError):
            self.slip.action_open_reverse_wizard()

    def test_success_returns_wizard_action(self):
        self.slip.write({
            'icici_payment_status': 'processing',
            'icici_file_seq_num': '7958579',
        })
        action = self.slip.action_open_reverse_wizard()

        self.assertEqual(action['res_model'], 'icici.reverse.wizard')
        self.assertEqual(action['context']['default_payslip_id'], self.slip.id)
        self.assertEqual(action['context']['default_file_seq_num'], '7958579')
