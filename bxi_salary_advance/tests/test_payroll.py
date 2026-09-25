import re
from datetime import timedelta

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import SalaryAdvanceCommon, month_start


@tagged('post_install', '-at_install')
class TestSalaryAdvancePayroll(SalaryAdvanceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_accounting()
        cls.structure = cls.env.ref('custom_payslip_report.structure_india_regular_pay')
        cls.rule = cls.env.ref('bxi_salary_advance.hr_rule_salary_advance')
        # The rules shipped by custom_payslip_report test "'CODE' in inputs", which the payroll
        # engine does not support (the databases carry corrected rules): use attribute access.
        for rule in cls.structure.rule_ids.filtered(lambda r: ' in inputs' in (r.amount_python_compute or '')):
            rule.amount_python_compute = re.sub(
                r"'(\w+)' in inputs", r"inputs.\1", rule.amount_python_compute)

    def _payslip(self, month, employee=None, deduction=0.0):
        employee = employee or self.employee
        slip = self.env['hr.payslip'].create({
            'name': 'Test payslip',
            'employee_id': employee.id,
            'date_from': month_start(month),
            'date_to': month_start(month, 1) - timedelta(days=1),
            'version_id': employee.version_id.id,
            'struct_id': self.structure.id,
        })
        if deduction:
            slip.input_line_ids = [(0, 0, {'name': 'Deduction', 'code': 'DEDUCTION', 'amount': deduction})]
        slip.compute_sheet()
        return slip

    def _line(self, slip, code):
        return sum(slip.line_ids.filtered(lambda line: line.code == code).mapped('total'))

    def _disbursed_advance(self, amount=45000, **vals):
        advance = self._approve(self._new_advance(amount=amount, **vals))
        return self._disburse(advance)

    def test_rule_added_to_structures(self):
        self.assertIn(self.rule, self.structure.rule_ids)

    def test_disbursement_schedule_and_entry(self):
        advance = self._disbursed_advance()
        self.assertEqual(advance.state, 'disbursed')
        self.assertEqual(advance.recovery_start, month_start(self.today, 1))
        self.assertEqual(advance.installment_ids.mapped('amount'), [15000, 15000, 15000])
        self.assertEqual(advance.installment_ids.mapped('due_date'),
                         [month_start(self.today, months) for months in (1, 2, 3)])
        self.assertEqual(advance.amount_balance, 45000)

        move = advance.disbursement_move_id
        self.assertEqual(move.state, 'posted')
        debit = move.line_ids.filtered(lambda line: line.debit)
        self.assertEqual(debit.account_id, self.advance_account)
        self.assertEqual(debit.partner_id, self.employee.work_contact_id)
        self.assertEqual(debit.debit, 45000)
        self.assertEqual(move.line_ids.filtered(lambda line: line.credit).account_id,
                         self.bank_journal.default_account_id)

    def test_housing_disbursement_credits_vendor(self):
        advance = self._approve(self._new_advance(category='housing', amount=60000, tenancy_months=6))
        advance._on_undertaking_signed()
        self._disburse(advance)
        credit = advance.disbursement_move_id.line_ids.filtered(lambda line: line.credit)
        self.assertEqual(credit.account_id, self.vendor_payable)
        self.assertEqual(credit.partner_id, self.vendor)
        self.assertEqual(advance.installment_ids.mapped('amount'), [10000] * 6)

    def test_last_emi_absorbs_rounding(self):
        advance = self._disbursed_advance(amount=10000)
        self.assertEqual(advance.installment_ids.mapped('amount'), [3333.33, 3333.33, 3333.34])

    def test_disbursement_without_journal_entry(self):
        advance = self._approve(self._new_advance())
        self._disburse(advance, create_entry=False)
        self.assertEqual(advance.state, 'disbursed')
        self.assertFalse(advance.disbursement_move_id)

    def test_no_deduction_before_recovery_starts(self):
        self._disbursed_advance()
        slip = self._payslip(self.today)
        self.assertFalse(self._line(slip, 'SAL_ADV'))

    def test_emi_deducted_from_payslip(self):
        advance = self._disbursed_advance()
        without = self._payslip(month_start(self.today, 1), employee=self.manager)
        slip = self._payslip(month_start(self.today, 1))
        self.assertEqual(self._line(slip, 'SAL_ADV'), -15000)
        self.assertAlmostEqual(slip.net_wage, without.net_wage - 15000)
        first = advance.installment_ids[0]
        self.assertEqual(first.payslip_id, slip)
        self.assertEqual(first.state, 'pending')

        slip.action_payslip_done()
        self.assertEqual(first.state, 'deducted')
        self.assertEqual(first.amount_recovered, 15000)
        self.assertEqual(advance.amount_recovered, 15000)
        self.assertEqual(advance.amount_balance, 30000)
        self.assertEqual(first.move_id.state, 'posted')
        credit = first.move_id.line_ids.filtered(lambda line: line.credit)
        self.assertEqual(credit.account_id, self.advance_account)
        self.assertEqual(credit.credit, 15000)
        self.assertEqual(first.move_id.line_ids.filtered(lambda line: line.debit).account_id, self.salary_payable)

    def test_cancelled_payslip_reverts_recovery(self):
        advance = self._disbursed_advance()
        slip = self._payslip(month_start(self.today, 1))
        slip.action_payslip_done()
        move = advance.installment_ids[0].move_id
        slip.action_payslip_cancel()
        first = advance.installment_ids[0]
        self.assertEqual(first.state, 'pending')
        self.assertFalse(first.move_id)
        self.assertTrue(move.reversal_move_ids)
        self.assertEqual(advance.amount_balance, 45000)
        # The EMI is picked up again by a new payslip of the same month.
        again = self._payslip(month_start(self.today, 1))
        self.assertEqual(self._line(again, 'SAL_ADV'), -15000)

    def test_missed_emi_is_recovered_later(self):
        advance = self._disbursed_advance()
        slip = self._payslip(month_start(self.today, 2))
        self.assertEqual(self._line(slip, 'SAL_ADV'), -30000)
        slip.action_payslip_done()
        self.assertEqual(advance.installment_ids.filtered(lambda i: i.state == 'deducted').mapped('sequence'), [1, 2])

    def test_net_pay_never_negative(self):
        advance = self._disbursed_advance()
        month = month_start(self.today, 1)
        reference = self._payslip(month, employee=self.manager)
        # Leave 5,000 of net pay before the salary advance EMI of 15,000.
        slip = self._payslip(month, deduction=reference.net_wage - 5000)
        self.assertAlmostEqual(slip.net_wage, 0.0)
        self.assertAlmostEqual(self._line(slip, 'SAL_ADV'), -5000)
        slip.action_payslip_done()
        first = advance.installment_ids.filtered(lambda i: i.sequence == 1 and i.state == 'deducted')
        self.assertAlmostEqual(first.amount_recovered, 5000)
        carried = advance.installment_ids.filtered(lambda i: i.origin_installment_id == first)
        self.assertAlmostEqual(carried.amount, 10000)
        self.assertEqual(carried.due_date, month_start(self.today, 2))
        self.assertAlmostEqual(advance.amount_balance, 40000)

        # Cancelling the payslip merges the carried-forward part back.
        slip.action_payslip_cancel()
        self.assertFalse(carried.exists())
        self.assertAlmostEqual(first.amount, 15000)
        self.assertEqual(first.state, 'pending')

    def test_nothing_recovered_defers_the_emi(self):
        advance = self._disbursed_advance()
        month = month_start(self.today, 1)
        reference = self._payslip(month, employee=self.manager)
        slip = self._payslip(month, deduction=reference.net_wage)
        self.assertFalse(self._line(slip, 'SAL_ADV'))
        slip.action_payslip_done()
        first = advance.installment_ids.filtered(lambda i: i.sequence == 1)
        self.assertEqual(first.state, 'pending')
        self.assertEqual(first.due_date, month_start(self.today, 2))
        self.assertFalse(first.payslip_id)

    def test_fully_recovered_advance_is_closed(self):
        advance = self._disbursed_advance()
        for months in (1, 2, 3):
            self._payslip(month_start(self.today, months)).action_payslip_done()
        self.assertEqual(advance.state, 'closed')
        self.assertEqual(advance.amount_balance, 0)
        lines = (advance.disbursement_move_id | advance.installment_ids.move_id).line_ids.filtered(
            lambda line: line.account_id == self.advance_account)
        self.assertTrue(all(lines.mapped('reconciled')))
        # A new advance is possible once the previous one is recovered.
        self._new_advance(amount=10000).action_submit()

    def test_credit_note_is_ignored(self):
        advance = self._disbursed_advance()
        slip = self._payslip(month_start(self.today, 1))
        slip.action_payslip_done()
        slip.refund_sheet()
        self.assertEqual(advance.installment_ids[0].state, 'deducted')
        self.assertEqual(advance.amount_recovered, 15000)

    # ── Full & Final Settlement ──────────────────────────────────────────
    def test_resignation_moves_balance_to_fnf(self):
        advance = self._disbursed_advance()
        self._payslip(month_start(self.today, 1)).action_payslip_done()
        last_day = month_start(self.today, 2) + timedelta(days=14)
        self._resign(self.employee, last_day, approve=True)
        self.assertEqual(advance.state, 'fnf')
        pending = advance.installment_ids.filtered(lambda i: i.state == 'pending')
        self.assertEqual(len(pending), 1)
        self.assertTrue(pending.is_fnf)
        self.assertEqual(pending.amount, 30000)
        self.assertEqual(pending.due_date, month_start(self.today, 2))

        final = self._payslip(month_start(self.today, 2))
        self.assertEqual(self._line(final, 'SAL_ADV'), -30000)
        final.action_payslip_done()
        self.assertEqual(advance.state, 'closed')

    def test_resignation_submission_keeps_recovery_going(self):
        advance = self._disbursed_advance()
        self._resign(self.employee, self.today + timedelta(days=60))
        self.assertEqual(advance.state, 'disbursed')

    def test_transfer_settled_by_hr(self):
        advance = self._disbursed_advance()
        with self.assertRaises(UserError):
            self.env['bxi.salary.advance.fnf.wizard'].with_user(self.finance_user).create({
                'advance_id': advance.id, 'last_day': self.today}).action_settle()
        self.env['bxi.salary.advance.fnf.wizard'].with_user(self.hr_user).create({
            'advance_id': advance.id, 'last_day': month_start(self.today, 1), 'reason': 'transfer',
        }).action_settle()
        self.assertEqual(advance.state, 'fnf')
        self.assertEqual(advance.installment_ids.filtered(lambda i: i.state == 'pending').amount, 45000)
        self.assertIn('Transfer', advance.message_ids[0].body)

    def test_employee_outstanding_balance(self):
        self._disbursed_advance()
        employee = self.employee.with_user(self.hr_user)
        self.assertEqual(employee.sa_outstanding_balance, 45000)
        self.assertEqual(employee.sa_advance_count, 1)
