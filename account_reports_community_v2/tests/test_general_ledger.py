from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestGeneralLedger(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env.ref('account_reports_community_v2.general_ledger_report')
        cls.expense_account = cls.company_data['default_account_expense']
        cls.revenue_account = cls.company_data['default_account_revenue']
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

    def _get_data(self, date_from, date_to, focus_account_id=None):
        options = {'date_from': date_from, 'date_to': date_to}
        if focus_account_id:
            options['focus_account_id'] = focus_account_id
            # Mirrors what the frontend does when a user expands an account
            # row: aml_rows are only populated for unfolded accounts, so the
            # account must be listed here to inspect its journal items.
            options['unfolded_line_ids'] = [focus_account_id]
        return self.report.action_get_report_data(options)

    def test_opening_plus_movement_equals_closing(self):
        data = self._get_data('2025-01-01', '2025-03-01', focus_account_id=self.expense_account.id)
        row = data['lines'][0]
        total_debit = sum(r['debit'] for r in row['aml_rows'])
        total_credit = sum(r['credit'] for r in row['aml_rows'])
        self.assertAlmostEqual(
            row['opening_balance'] + total_debit - total_credit,
            row['closing_balance'],
            places=2,
        )

    def test_running_balance_matches_final_closing(self):
        data = self._get_data('2025-01-01', '2025-03-01', focus_account_id=self.expense_account.id)
        row = data['lines'][0]
        self.assertTrue(row['aml_rows'], "Expected journal items for the expense account")
        self.assertAlmostEqual(row['aml_rows'][-1]['running_balance'], row['closing_balance'], places=2)

    def test_period_continuity(self):
        """Closing balance of period 1 must equal opening balance of period 2 for the same account."""
        period_1 = self._get_data('2025-01-01', '2025-01-31', focus_account_id=self.expense_account.id)
        period_2 = self._get_data('2025-02-01', '2025-02-28', focus_account_id=self.expense_account.id)
        self.assertAlmostEqual(
            period_1['lines'][0]['closing_balance'],
            period_2['lines'][0]['opening_balance'],
            places=2,
        )

    def test_focus_account_filters_to_single_account(self):
        data = self._get_data('2025-01-01', '2025-03-01', focus_account_id=self.expense_account.id)
        self.assertEqual(len(data['lines']), 1)
        self.assertEqual(data['lines'][0]['account_id'], self.expense_account.id)

    def test_small_account_has_no_more_pages(self):
        """Regression guard: a normal-sized account (this test's own fixture
        data, well under AML_PAGE_SIZE) must report aml_rows_has_more=False,
        not just omit the field."""
        data = self._get_data('2025-01-01', '2025-03-01', focus_account_id=self.expense_account.id)
        row = data['lines'][0]
        self.assertFalse(row['aml_rows_has_more'])

    def test_account_over_page_size_paginates_via_load_more(self):
        """An account with more than AML_PAGE_SIZE journal items must return
        exactly one page on the initial fetch (has_more=True), and
        action_get_more_aml_rows (the "Load more" RPC) must return the rest,
        continuing the running balance from where the first page left off -
        not resetting it back to the account's opening balance."""
        from odoo.addons.account_reports_community_v2.models.account_report_engine import AML_PAGE_SIZE

        journal = self.company_data['default_journal_misc']
        total_lines = AML_PAGE_SIZE + 15
        for i in range(total_lines):
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': journal.id,
                'date': '2025-03-15',
                'line_ids': [
                    (0, 0, {'account_id': self.expense_account.id, 'debit': 1.0, 'credit': 0.0}),
                    (0, 0, {'account_id': self.revenue_account.id, 'debit': 0.0, 'credit': 1.0}),
                ],
            })
            move.action_post()

        # Total matching rows for this account/period, not just total_lines:
        # setUpClass's own move_1/move_2 also debit expense_account within
        # 2025-01-01..2025-04-01, so the true total is total_lines + those,
        # not total_lines alone.
        total_matching = self.env['account.move.line'].search_count([
            ('account_id', '=', self.expense_account.id),
            ('parent_state', '=', 'posted'),
            ('date', '>=', '2025-01-01'), ('date', '<=', '2025-04-01'),
        ])

        data = self._get_data('2025-01-01', '2025-04-01', focus_account_id=self.expense_account.id)
        row = data['lines'][0]
        self.assertEqual(len(row['aml_rows']), AML_PAGE_SIZE)
        self.assertTrue(row['aml_rows_has_more'])

        last_row = row['aml_rows'][-1]
        more = self.report.action_get_more_aml_rows(
            options={'date_from': '2025-01-01', 'date_to': '2025-04-01'},
            group_id=self.expense_account.id,
            after_id=last_row['id'],
            after_date=last_row['date'],
            after_running_balance=last_row['running_balance'],
        )
        self.assertEqual(len(more['aml_rows']), total_matching - AML_PAGE_SIZE)
        self.assertFalse(more['aml_rows_has_more'])
        # No overlap and no gap between the two pages.
        self.assertEqual(more['aml_rows'][0]['id'], self.env['account.move.line'].search(
            [('account_id', '=', self.expense_account.id), ('id', '>', last_row['id'])],
            order='date, id', limit=1,
        ).id)
        self.assertAlmostEqual(more['aml_rows'][-1]['running_balance'], row['closing_balance'], places=2)

    def test_foreign_currency_amount_shown_on_row(self):
        """A foreign-currency transaction must carry its original amount
        alongside the company-currency figures every other column already
        uses - same-currency rows (move_1/move_2 from setUpClass) must NOT
        carry one, since there's nothing foreign to show."""
        # search() only returns active=True records by default, but a
        # fresh company only has its own currency active (Odoo's "no
        # accidental multi-currency database" default) - active_test=False
        # is needed to find an *inactive* other currency to then activate,
        # otherwise this search silently returns nothing to activate.
        foreign_currency = self.env['res.currency'].with_context(active_test=False).search(
            [('id', '!=', self.env.company.currency_id.id)], limit=1,
        )
        self.assertTrue(foreign_currency, "Expected at least one other currency to exist in res.currency")
        foreign_currency.active = True
        self.env['res.currency.rate'].create({
            'currency_id': foreign_currency.id,
            'name': '2025-01-15',
            'rate': 2.0,
            'company_id': self.env.company.id,
        })
        journal = self.company_data['default_journal_misc']
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': '2025-01-15',
            'line_ids': [
                (0, 0, {
                    'account_id': self.expense_account.id, 'debit': 50.0, 'credit': 0.0,
                    'currency_id': foreign_currency.id, 'amount_currency': 100.0,
                }),
                (0, 0, {'account_id': self.revenue_account.id, 'debit': 0.0, 'credit': 50.0}),
            ],
        })
        move.action_post()
        foreign_line = move.line_ids.filtered(lambda l: l.account_id == self.expense_account)

        data = self._get_data('2025-01-01', '2025-03-01', focus_account_id=self.expense_account.id)
        row = data['lines'][0]

        foreign_row = next(r for r in row['aml_rows'] if r['id'] == foreign_line.id)
        self.assertEqual(foreign_row['foreign_currency_name'], foreign_currency.name)
        self.assertAlmostEqual(foreign_row['amount_currency'], foreign_line.amount_currency, places=2)

        same_currency_row = next(r for r in row['aml_rows'] if r['id'] != foreign_line.id)
        self.assertIsNone(same_currency_row['foreign_currency_name'])
        self.assertIsNone(same_currency_row['amount_currency'])
