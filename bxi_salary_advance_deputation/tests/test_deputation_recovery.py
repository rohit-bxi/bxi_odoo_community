from ast import literal_eval
from datetime import timedelta

from odoo.tests import tagged

from odoo.addons.bxi_salary_advance.tests.common import SalaryAdvanceCommon, month_start


@tagged('post_install', '-at_install')
class TestDeputationRecovery(SalaryAdvanceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_accounting()
        # Germany follows the Calendar Days approach: the home payroll ends the day before arrival.
        cls.arrival = month_start(cls.today) + timedelta(days=14)
        cls.host_account = cls.env['account.account'].create({
            'code': 'SA1399', 'name': 'Inter-company receivable', 'account_type': 'asset_current'})

    def _deputation(self):
        deputation = self.env['bxi.deputation'].create({
            'employee_id': self.employee.id,
            'host_country_id': self.env.ref('base.de').id,
            'planned_start_date': self.arrival,
        })
        deputation.action_approve()
        deputation.arrival_date = self.arrival
        deputation.action_confirm_arrival()
        return deputation

    def _disbursed_advance(self):
        return self._disburse(self._approve(self._new_advance(amount=45000)), when=month_start(self.today, -1))

    def test_balance_recovered_from_last_home_payslip(self):
        advance = self._disbursed_advance()
        deputation = self._deputation()
        self.assertEqual(deputation.home_last_date, self.arrival - timedelta(days=1))
        self.assertEqual(advance.state, 'fnf')
        pending = advance.installment_ids.filtered(lambda inst: inst.state == 'pending')
        self.assertEqual(pending.mapped('due_date'), [month_start(self.today)])
        self.assertEqual(sum(pending.mapped('amount')), 45000)
        self.assertTrue(pending.is_fnf)
        self.assertFalse(advance.recover_at_host)

    def test_balance_after_last_home_payslip_recovered_at_host(self):
        advance = self._disbursed_advance()
        # The payroll of the last home month is already confirmed.
        slip = self.env['hr.payslip'].create({
            'name': 'Confirmed payslip',
            'employee_id': self.employee.id,
            'date_from': month_start(self.today),
            'date_to': month_start(self.today, 1) - timedelta(days=1),
            'version_id': self.employee.version_id.id,
        })
        slip.state = 'done'
        self._deputation()
        self.assertEqual(advance.state, 'fnf')
        self.assertTrue(advance.recover_at_host)
        action = self.env['ir.actions.act_window']._for_xml_id(
            'bxi_salary_advance_deputation.action_bxi_salary_advance_recover_at_host')
        self.assertIn(advance, self.env['bxi.salary.advance'].search(literal_eval(action['domain'])))

        wizard = self.env['bxi.salary.advance.host.recovery.wizard'].with_user(self.hr_user).create({
            'advance_id': advance.id,
            'reference': 'UK-PAYSLIP-001',
            'post_entry': True,
            'counterpart_account_id': self.host_account.id,
        })
        self.assertEqual(wizard.amount, 45000)
        wizard.action_confirm()
        self.assertEqual(advance.state, 'closed')
        self.assertEqual(advance.amount_balance, 0)
        self.assertFalse(advance.recover_at_host)
        move = advance.installment_ids.move_id
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.line_ids.filtered(lambda l: l.account_id == self.advance_account).credit, 45000)

    def test_request_under_approval_is_flagged_to_hr(self):
        advance = self._new_advance(amount=30000)
        advance.action_submit()
        advance.with_user(self.manager.user_id).action_rm_approve()
        self._deputation()
        self.assertEqual(advance.state, 'hr_review')
        self.assertTrue(advance.activity_ids.filtered(lambda act: 'deputation' in (act.summary or '')))
