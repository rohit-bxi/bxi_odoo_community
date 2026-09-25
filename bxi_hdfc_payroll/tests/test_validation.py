# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import HdfcPayrollCommon


@tagged('post_install', '-at_install')
class TestHdfcValidation(HdfcPayrollCommon):

    def test_errors_are_collected(self):
        ok = self._create_employee('Asha', [('50100000000001', self.hdfc_bank, True)])
        no_account = self._create_employee('Bala')
        untrusted = self._create_employee('Chitra', [('30000000000003', self.sbi_bank, False)])
        slips = (
            self._create_payslip(ok, 50000, state='draft')
            | self._create_payslip(no_account, 40000)
            | self._create_payslip(untrusted, 30000)
            | self._create_payslip(ok, 1000, credit_note=True)
        )
        _lines, errors = slips._hdfc_prepare_payout()
        text = '\n'.join(errors)
        self.assertIn('must be done', text)
        self.assertIn('no bank account', text)
        self.assertIn('not trusted', text)
        self.assertIn('refund', text)
        with self.assertRaises(UserError):
            self._release(slips)

    def test_invalid_ifsc_and_account_number(self):
        bad_bank = self.env['res.bank'].create({'name': 'Bad', 'bic': 'XYZ123'})
        employee = self._create_employee('Deepak', [('12AB', bad_bank, True)])
        _lines, errors = self._create_payslip(employee, 1000)._hdfc_prepare_payout()
        text = '\n'.join(errors)
        self.assertIn('9 to 18 digits', text)
        self.assertIn('IFSC', text)

    def test_missing_config_setup(self):
        self.config.journal_id = False
        employee = self._create_employee('Esha', [('50100000000005', self.hdfc_bank, True)])
        _lines, errors = self._create_payslip(employee, 1000)._hdfc_prepare_payout()
        self.assertTrue(any('bank journal' in e for e in errors))

    def test_transfer_mode(self):
        self.assertEqual(self.config._get_txn_type('HDFC0001234', 500000), 'internal')
        self.assertEqual(self.config._get_txn_type('SBIN0005678', 199999.99), 'neft')
        self.assertEqual(self.config._get_txn_type('SBIN0005678', 200000), 'rtgs')
        self.config.allow_imps = True
        self.assertEqual(self.config._get_txn_type('SBIN0005678', 1000), 'imps')

    def test_salary_distribution_split(self):
        employee = self._create_employee(
            'Farhan',
            [('50100000000006', self.hdfc_bank, True), ('30000000000006', self.sbi_bank, True),
             ('30000000000007', self.sbi_bank, True)],
            distribution={
                0: {'sequence': 1, 'amount': 10000.0, 'amount_is_percentage': False},
                1: {'sequence': 2, 'amount': 33.33, 'amount_is_percentage': True},
                2: {'sequence': 3, 'amount': 66.67, 'amount_is_percentage': True},
            },
        )
        slip = self._create_payslip(employee, 55555.55)
        split, errors = slip._hdfc_split_amount(self.config)
        self.assertFalse(errors)
        amounts = [amount for _account, amount in split]
        self.assertEqual(amounts[0], 10000.0)
        self.assertEqual(amounts[1], 15183.66)  # 33.33 % of 45555.55
        self.assertAlmostEqual(sum(amounts), 55555.55, places=2)
        self.assertEqual(amounts[2], 30371.89)  # remainder

    def test_fixed_amount_capped_by_net(self):
        employee = self._create_employee(
            'Gita',
            [('50100000000008', self.hdfc_bank, True), ('30000000000008', self.sbi_bank, True)],
            distribution={
                0: {'sequence': 1, 'amount': 80000.0, 'amount_is_percentage': False},
                1: {'sequence': 2, 'amount': 100.0, 'amount_is_percentage': True},
            },
        )
        split, _errors = self._create_payslip(employee, 50000)._hdfc_split_amount(self.config)
        self.assertEqual([amount for _account, amount in split], [50000.0])

    def test_already_in_active_batch(self):
        employee = self._create_employee('Hari', [('50100000000009', self.hdfc_bank, True)])
        slip = self._create_payslip(employee, 20000)
        self._release(slip)
        self.assertEqual(slip.hdfc_payment_state, 'in_batch')
        with self.assertRaises(UserError):
            slip.action_hdfc_release()
