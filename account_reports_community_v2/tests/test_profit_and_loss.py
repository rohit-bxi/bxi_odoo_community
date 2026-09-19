from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


def _flatten_values(lines, period_index=0):
    result = {}
    for line in lines:
        for col in line['periods'][period_index]['columns']:
            result[line['code']] = col['value']
        result.update(_flatten_values(line.get('children') or [], period_index=period_index))
    return result


@tagged('post_install', '-at_install')
class TestProfitAndLoss(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env.ref('account_reports_community_v2.profit_and_loss_report')
        cls.expense_account = cls.company_data['default_account_expense']
        cls.revenue_account = cls.company_data['default_account_revenue']
        receivable_account = cls.company_data['default_account_receivable']
        journal = cls.company_data['default_journal_misc']

        move = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': '2025-01-15',
            'line_ids': [
                (0, 0, {'account_id': cls.expense_account.id, 'debit': 40.0, 'credit': 0.0}),
                (0, 0, {'account_id': receivable_account.id, 'debit': 60.0, 'credit': 0.0}),
                (0, 0, {'account_id': cls.revenue_account.id, 'debit': 0.0, 'credit': 100.0}),
            ],
        })
        move.action_post()

    def _get_values(self):
        data = self.report.action_get_report_data({'date_from': '2025-01-01', 'date_to': '2025-03-01'})
        return _flatten_values(data['lines'])

    def test_net_profit_matches_manual_calc(self):
        values = self._get_values()
        self.assertAlmostEqual(values['PL_NET_PROFIT'], 60.0, places=2)

    def test_totals_match_manual_read_group(self):
        values = self._get_values()

        income_result = self.env['account.move.line']._read_group(
            [
                ('account_id.account_type', '=', 'income'),
                ('parent_state', '=', 'posted'),
                ('date', '>=', '2025-01-01'), ('date', '<=', '2025-03-01'),
            ],
            aggregates=['balance:sum'],
        )
        manual_income = -(income_result[0][0] or 0.0)  # credit-normal: negate to read as positive revenue
        self.assertAlmostEqual(values['PL_INCOME_TOTAL'], manual_income, places=2)

        expense_result = self.env['account.move.line']._read_group(
            [
                ('account_id.account_type', '=', 'expense'),
                ('parent_state', '=', 'posted'),
                ('date', '>=', '2025-01-01'), ('date', '<=', '2025-03-01'),
            ],
            aggregates=['balance:sum'],
        )
        manual_expense = expense_result[0][0] or 0.0
        self.assertAlmostEqual(values['PL_EXPENSE_TOTAL'], manual_expense, places=2)

    def test_category_collapses_by_default(self):
        data = self.report.action_get_report_data({'date_from': '2025-01-01', 'date_to': '2025-03-01'})
        expenses_section = next(line for line in data['lines'] if line['code'] == 'PL_EXPENSES')
        operating_expenses = next(
            line for line in expenses_section['children'] if line['code'] == 'PL_EXPENSE_OPERATING'
        )
        self.assertFalse(operating_expenses['unfolded'])
        self.assertEqual(operating_expenses['children'], [])
        self.assertNotEqual(operating_expenses['periods'][0]['columns'][0]['value'], None)

    def test_category_expands_into_accounts_with_codes(self):
        """Expanding 'Operating Expenses' must list the expense account
        moved in setUpClass, with its code and an account_id."""
        operating_expenses_line = self.env.ref('account_reports_community_v2.pl_line_expense_operating')
        data = self.report.action_get_report_data({
            'date_from': '2025-01-01', 'date_to': '2025-03-01',
            'unfolded_line_ids': [operating_expenses_line.id],
        })
        expenses_section = next(line for line in data['lines'] if line['code'] == 'PL_EXPENSES')
        operating_expenses = next(
            line for line in expenses_section['children'] if line['code'] == 'PL_EXPENSE_OPERATING'
        )
        self.assertTrue(operating_expenses['unfolded'])
        self.assertTrue(operating_expenses['children'])
        for account_row in operating_expenses['children']:
            self.assertTrue(account_row['account_id'])
            self.assertTrue(account_row['code'])
            self.assertIn(account_row['code'], account_row['name'])
