from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo.tests import tagged

from .common import TrainingCommon


@tagged('post_install', '-at_install')
class TestTrainingPayroll(TrainingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_accounting()
        cls.rule = cls.env.ref('bxi_training_policy.hr_rule_training_recovery')
        # A minimal structure: basic = wage, training recovery, net.
        Rule = cls.env['hr.salary.rule']
        basic = Rule.create({
            'name': 'Basic', 'code': 'BASIC', 'sequence': 1, 'category_id': cls.env.ref('om_hr_payroll.BASIC').id,
            'amount_select': 'code', 'amount_python_compute': 'result = contract.wage',
        })
        net = Rule.create({
            'name': 'Net', 'code': 'NET', 'sequence': 200, 'category_id': cls.env.ref('om_hr_payroll.NET').id,
            'amount_select': 'code',
            'amount_python_compute': 'result = categories.BASIC + categories.ALW + categories.DED',
        })
        # No parent structure: om_hr_payroll merges parent structures in set order, so a parent with
        # its own BASIC rule would make the computed basic salary depend on the run.
        cls.structure = cls.env['hr.payroll.structure'].create({
            'name': 'Training Test Structure', 'code': 'TRNTEST', 'parent_id': False,
            'rule_ids': [(6, 0, (basic | cls.rule | net).ids)],
        })
        cls.employee.version_id.wage = 50000
        cls.manager.version_id.wage = 50000

    def _month_start(self, months=0):
        return (self.today + relativedelta(months=months)).replace(day=1)

    def _payslip(self, month_start, employee=None):
        employee = employee or self.employee
        slip = self.env['hr.payslip'].create({
            'name': 'Test payslip',
            'employee_id': employee.id,
            'date_from': month_start,
            'date_to': month_start + relativedelta(months=1) - timedelta(days=1),
            'version_id': employee.version_id.id,
            'struct_id': self.structure.id,
        })
        slip.compute_sheet()
        return slip

    def _line(self, slip):
        return sum(slip.line_ids.filtered(lambda line: line.code == 'TRAIN_REC').mapped('total'))

    def _breach(self, fee=40000, lodging=20000):
        training = self._ready(self._new_training(fee=fee, lodging=lodging))
        self._complete(training, end_date=self.today - relativedelta(days=10))
        self._resign(self.employee, self.today + relativedelta(days=5), approve=True)
        return training.agreement_id.recovery_ids

    def test_rule_added_to_existing_structures(self):
        # The post-init hook adds the recovery rule to every salary structure
        # that exists when the module is installed. Assert that contract by
        # re-running the (idempotent) hook, rather than guessing which of the
        # current structures predate the install from their create_date.
        from odoo.addons.bxi_training_policy import _post_init_hook
        _post_init_hook(self.env)
        for structure in self.env['hr.payroll.structure'].search([]):
            self.assertIn(self.rule, structure.rule_ids, structure.name)

    def test_recovered_in_final_settlement(self):
        recovery = self._breach(fee=20000, lodging=15000)
        month = recovery.payroll_month
        without = self._payslip(month, employee=self.manager)
        slip = self._payslip(month)
        self.assertEqual(self._line(slip), -35000)
        self.assertAlmostEqual(slip.net_wage, without.net_wage - 35000)
        slip.action_payslip_done()
        self.assertEqual(recovery.amount_recovered, 35000)
        self.assertEqual(recovery.state, 'recovered')
        self.assertEqual(recovery.agreement_id.state, 'recovered')
        move = recovery.line_ids.move_id
        self.assertEqual(move.line_ids.filtered('debit').account_id, self.salary_payable)
        self.assertEqual(move.line_ids.filtered('credit').account_id, self.bonded_account)

    def test_shortfall_moves_to_legal(self):
        recovery = self._breach(fee=90000, lodging=60000)
        slip = self._payslip(recovery.payroll_month)
        deducted = -self._line(slip)
        self.assertGreater(deducted, 0)
        self.assertLess(deducted, 150000)
        self.assertGreaterEqual(slip.net_wage, 0)
        slip.action_payslip_done()
        self.assertEqual(recovery.state, 'legal')
        self.assertAlmostEqual(recovery.balance, 150000 - deducted)

    def test_cancelled_payslip_reverts_recovery(self):
        recovery = self._breach(fee=20000, lodging=15000)
        slip = self._payslip(recovery.payroll_month)
        slip.action_payslip_done()
        move = recovery.line_ids.move_id
        slip.action_payslip_cancel()
        self.assertFalse(recovery.line_ids)
        self.assertEqual(recovery.state, 'payroll')
        self.assertEqual(recovery.balance, 35000)
        self.assertEqual(recovery.agreement_id.state, 'breached')
        self.assertTrue(move.reversal_move_ids)

    def test_unspent_advance_recovered_next_month(self):
        training = self._ready(self._new_training(fee=10000, lodging=8000))
        self._pay_advance(training)
        self._complete(training)
        self._add_claim_line(training, self.lodging_product, 5000)
        training.with_user(self.employee.user_id).action_submit_claim()
        self._approve_claim(training)
        training.expense_ids.with_user(self.finance_user).action_finance_approved()
        recovery = training.recovery_ids
        self.assertEqual(recovery.amount_due, 3000)
        self.assertEqual(recovery.payroll_month, self._month_start(1))
        self.assertFalse(self._line(self._payslip(self._month_start())))
        slip = self._payslip(self._month_start(1))
        self.assertEqual(self._line(slip), -3000)
        slip.action_payslip_done()
        self.assertEqual(recovery.state, 'recovered')
        credit = recovery.line_ids.move_id.line_ids.filtered('credit')
        self.assertEqual(credit.account_id, self.advance_account)
