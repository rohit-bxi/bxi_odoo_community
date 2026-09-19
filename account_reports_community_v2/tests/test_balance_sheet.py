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
class TestBalanceSheet(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env.ref('account_reports_community_v2.balance_sheet_report')
        expense_account = cls.company_data['default_account_expense']
        revenue_account = cls.company_data['default_account_revenue']
        receivable_account = cls.company_data['default_account_receivable']
        journal = cls.company_data['default_journal_misc']

        move = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': '2025-01-15',
            'line_ids': [
                (0, 0, {'account_id': expense_account.id, 'debit': 40.0, 'credit': 0.0}),
                (0, 0, {'account_id': receivable_account.id, 'debit': 60.0, 'credit': 0.0}),
                (0, 0, {'account_id': revenue_account.id, 'debit': 0.0, 'credit': 100.0}),
            ],
        })
        move.action_post()

    def _get_values(self):
        data = self.report.action_get_report_data({'date_from': '2025-01-01', 'date_to': '2025-03-01'})
        return _flatten_values(data['lines'])

    def test_assets_equal_liabilities_plus_equity(self):
        """Fundamental accounting identity: Assets = Liabilities + Equity, for
        ANY balanced set of double-entry postings, precisely because
        'Current Year Earnings' folds income/expense movement into equity."""
        values = self._get_values()
        self.assertAlmostEqual(values['BS_ASSETS_TOTAL'], values['BS_LIAB_EQUITY_TOTAL'], places=2)

    def test_current_year_earnings_matches_net_movement(self):
        values = self._get_values()
        # revenue (100) - expense (40) = 60, booked as Current Year Earnings
        self.assertAlmostEqual(values['BS_CURRENT_EARNINGS'], 60.0, places=2)

    def test_category_collapses_by_default(self):
        """Leaf categories (Current Assets, Equity, ...) must start
        collapsed - only the account.report.line and Total lines exist
        server-side; the account breakdown is opt-in."""
        data = self.report.action_get_report_data({'date_from': '2025-01-01', 'date_to': '2025-03-01'})
        assets_section = next(line for line in data['lines'] if line['code'] == 'BS_ASSETS')
        current_assets = next(line for line in assets_section['children'] if line['code'] == 'BS_ASSETS_CURRENT')
        self.assertFalse(current_assets['unfolded'])
        self.assertEqual(current_assets['children'], [])
        # But its own total must still be visible while collapsed.
        self.assertNotEqual(current_assets['periods'][0]['columns'][0]['value'], None)

    def test_category_expands_into_accounts_with_codes(self):
        """Expanding 'Current Assets' must list the individual accounts
        behind it (the receivable account moved in setUpClass), each
        carrying its account code and an account_id (which is what makes
        the drill-down menu appear on that row)."""
        current_assets_line = self.env.ref('account_reports_community_v2.bs_line_assets_current')
        data = self.report.action_get_report_data({
            'date_from': '2025-01-01', 'date_to': '2025-03-01',
            'unfolded_line_ids': [current_assets_line.id],
        })
        assets_section = next(line for line in data['lines'] if line['code'] == 'BS_ASSETS')
        current_assets_row = next(line for line in assets_section['children'] if line['code'] == 'BS_ASSETS_CURRENT')
        self.assertTrue(current_assets_row['unfolded'])
        self.assertTrue(current_assets_row['children'], "Expected at least the receivable account to show up")
        for account_row in current_assets_row['children']:
            self.assertTrue(account_row['account_id'])
            self.assertTrue(account_row['code'])
            self.assertIn(account_row['code'], account_row['name'])
