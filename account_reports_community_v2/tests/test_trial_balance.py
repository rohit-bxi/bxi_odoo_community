from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


def _row_values(row, period_index=0):
    return {col['expression_label']: col['value'] for col in row['periods'][period_index]['columns']}


@tagged('post_install', '-at_install')
class TestTrialBalance(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env.ref('account_reports_community_v2.trial_balance_report')
        cls.revenue_account = cls.company_data['default_account_revenue']
        cls.expense_account = cls.company_data['default_account_expense']
        journal = cls.company_data['default_journal_misc']

        cls.move_1 = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': '2025-01-15',
            'line_ids': [
                (0, 0, {'account_id': cls.expense_account.id, 'debit': 100.0, 'credit': 0.0}),
                (0, 0, {'account_id': cls.revenue_account.id, 'debit': 0.0, 'credit': 100.0}),
            ],
        })
        cls.move_1.action_post()

        cls.move_2 = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': '2025-02-15',
            'line_ids': [
                (0, 0, {'account_id': cls.expense_account.id, 'debit': 50.0, 'credit': 0.0}),
                (0, 0, {'account_id': cls.revenue_account.id, 'debit': 0.0, 'credit': 50.0}),
            ],
        })
        cls.move_2.action_post()

    def _get_data(self, **extra_options):
        options = {'date_from': '2025-01-01', 'date_to': '2025-03-01'}
        options.update(extra_options)
        return self.report.action_get_report_data(options)

    def test_line_internal_consistency(self):
        """initial_balance + period_debit - period_credit must equal end_balance, per account row."""
        accounts_line = self._get_data()['lines'][0]
        self.assertTrue(accounts_line['children'], "Trial balance should list at least one account row")
        for row in accounts_line['children']:
            values = _row_values(row)
            computed_end = values['initial_balance'] + values['period_debit'] - values['period_credit']
            self.assertAlmostEqual(
                computed_end, values['end_balance'], places=2,
                msg=f"Inconsistent balance for {row['name']}",
            )

    def test_matches_manual_sum(self):
        """end_balance must match an independent manual _read_group sum on account.move.line."""
        accounts_line = self._get_data()['lines'][0]
        row = next(r for r in accounts_line['children'] if r['account_id'] == self.expense_account.id)
        values = _row_values(row)

        result = self.env['account.move.line']._read_group(
            [
                ('account_id', '=', self.expense_account.id),
                ('parent_state', '=', 'posted'),
                ('date', '<=', '2025-03-01'),
            ],
            aggregates=['balance:sum'],
        )
        manual_balance = result[0][0] or 0.0
        self.assertAlmostEqual(values['end_balance'], manual_balance, places=2)

    def test_trial_balance_nets_to_zero(self):
        """Sum of end_balance across every account is zero: the fundamental double-entry invariant."""
        accounts_line = self._get_data()['lines'][0]
        total = sum(
            col['value']
            for row in accounts_line['children']
            for col in row['periods'][0]['columns']
            if col['expression_label'] == 'end_balance'
        )
        self.assertAlmostEqual(total, 0.0, places=2)

    def test_journal_filter_excludes_other_journals(self):
        """Filtering to a journal with no entries must show no movement at all."""
        other_journal = self.env['account.journal'].create({
            'name': 'Other Journal',
            'type': 'general',
            'code': 'OTHJ',
            'company_id': self.env.company.id,
        })
        data = self._get_data(journal_ids=[other_journal.id])
        self.assertFalse(data['lines'][0]['children'], "No accounts should show movement for an unused journal")

    def test_all_entries_includes_draft_moves(self):
        """Draft moves should only affect the report once 'all_entries' is set."""
        journal = self.company_data['default_journal_misc']
        self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': '2025-01-20',
            'line_ids': [
                (0, 0, {'account_id': self.expense_account.id, 'debit': 999.0, 'credit': 0.0}),
                (0, 0, {'account_id': self.revenue_account.id, 'debit': 0.0, 'credit': 999.0}),
            ],
        })  # left in draft on purpose, never posted

        def expense_end_balance(data):
            row = next(r for r in data['lines'][0]['children'] if r['account_id'] == self.expense_account.id)
            return _row_values(row)['end_balance']

        posted_only = self._get_data()
        all_entries = self._get_data(all_entries=True)
        self.assertAlmostEqual(
            expense_end_balance(all_entries) - expense_end_balance(posted_only), 999.0, places=2,
        )

    def test_search_filters_accounts_by_code(self):
        data = self._get_data(search=self.expense_account.code)
        account_ids = {row['account_id'] for row in data['lines'][0]['children']}
        self.assertEqual(account_ids, {self.expense_account.id})

    def test_comparison_period_returns_two_periods_with_shifted_dates(self):
        """comparison_periods=1 must return the current period plus exactly
        one prior period of the same length, with correctly shifted dates."""
        data = self._get_data(comparison_periods=1)
        accounts_line = data['lines'][0]
        row = next(r for r in accounts_line['children'] if r['account_id'] == self.expense_account.id)
        self.assertEqual(len(row['periods']), 2)

        current_period, previous_period = row['periods']
        self.assertEqual(current_period['date_from'], '2025-01-01')
        self.assertEqual(current_period['date_to'], '2025-03-01')
        # Previous period is the same length (60 days), immediately preceding.
        self.assertEqual(previous_period['date_to'], '2024-12-31')
        self.assertEqual(previous_period['date_from'], '2024-11-02')

    def test_comparison_previous_period_has_no_movement(self):
        """The previous period (before any postings existed) should show a
        zero end_balance for the expense account, distinct from the current
        period's non-zero value."""
        data = self._get_data(comparison_periods=1)
        row = next(r for r in data['lines'][0]['children'] if r['account_id'] == self.expense_account.id)
        current_values = _row_values(row, period_index=0)
        previous_values = _row_values(row, period_index=1)
        self.assertNotEqual(current_values['end_balance'], 0.0)
        self.assertAlmostEqual(previous_values['end_balance'], 0.0, places=2)

    def test_comparison_month_granularity_aligns_to_calendar_month(self):
        """A raw day-count shift back from Feb (28 days) would land mid-January;
        with period_granularity='month' it must land on exactly Jan 1-31."""
        data = self._get_data(
            date_from='2025-02-01', date_to='2025-02-28',
            comparison_periods=1, period_granularity='month',
        )
        _current, previous = data['lines'][0]['periods']
        self.assertEqual(previous['date_from'], '2025-01-01')
        self.assertEqual(previous['date_to'], '2025-01-31')

    def test_comparison_quarter_granularity_aligns_to_calendar_quarter(self):
        data = self._get_data(
            date_from='2025-01-01', date_to='2025-03-31',
            comparison_periods=1, period_granularity='quarter',
        )
        _current, previous = data['lines'][0]['periods']
        self.assertEqual(previous['date_from'], '2024-10-01')
        self.assertEqual(previous['date_to'], '2024-12-31')

    def test_comparison_year_granularity_aligns_to_calendar_year(self):
        data = self._get_data(
            date_from='2025-01-01', date_to='2025-12-31',
            comparison_periods=1, period_granularity='year',
        )
        _current, previous = data['lines'][0]['periods']
        self.assertEqual(previous['date_from'], '2024-01-01')
        self.assertEqual(previous['date_to'], '2024-12-31')
