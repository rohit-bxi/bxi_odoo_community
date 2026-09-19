from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestAgedPartnerBalance(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.receivable_report = cls.env.ref('account_reports_community_v2.aged_receivable_report')
        cls.payable_report = cls.env.ref('account_reports_community_v2.aged_payable_report')
        cls.receivable_account = cls.company_data['default_account_receivable']
        cls.payable_account = cls.company_data['default_account_payable']
        cls.revenue_account = cls.company_data['default_account_revenue']
        cls.expense_account = cls.company_data['default_account_expense']
        journal = cls.company_data['default_journal_misc']

        # Not-due invoice: dated 2025-03-01, due 2025-04-15 (future relative to as-of date below).
        cls.move_not_due = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': '2025-03-01',
            'line_ids': [
                (0, 0, {
                    'account_id': cls.receivable_account.id, 'partner_id': cls.partner_a.id,
                    'debit': 100.0, 'credit': 0.0, 'date_maturity': '2025-04-15',
                }),
                (0, 0, {'account_id': cls.revenue_account.id, 'debit': 0.0, 'credit': 100.0}),
            ],
        })
        cls.move_not_due.action_post()

        # Overdue invoice: due 2025-01-15, 45 days overdue as of 2025-03-01 -> 31-60 bucket.
        cls.move_overdue = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': '2025-01-01',
            'line_ids': [
                (0, 0, {
                    'account_id': cls.receivable_account.id, 'partner_id': cls.partner_a.id,
                    'debit': 200.0, 'credit': 0.0, 'date_maturity': '2025-01-15',
                }),
                (0, 0, {'account_id': cls.revenue_account.id, 'debit': 0.0, 'credit': 200.0}),
            ],
        })
        cls.move_overdue.action_post()

        # Overdue bill for a different partner, on the payable side.
        cls.move_payable = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': '2025-01-01',
            'line_ids': [
                (0, 0, {
                    'account_id': cls.payable_account.id, 'partner_id': cls.partner_b.id,
                    'debit': 0.0, 'credit': 150.0, 'date_maturity': '2025-01-10',
                }),
                (0, 0, {'account_id': cls.expense_account.id, 'debit': 150.0, 'credit': 0.0}),
            ],
        })
        cls.move_payable.action_post()

    def test_not_due_and_overdue_buckets(self):
        """As of 2025-03-01: the Jan invoice (due Jan 15) is 45 days overdue
        -> 31-60 bucket; the Mar invoice (due Apr 15) isn't due yet -> Not Due."""
        data = self.receivable_report.action_get_report_data({'date_to': '2025-03-01'})
        row = next(r for r in data['lines'] if r['partner_id'] == self.partner_a.id)
        self.assertAlmostEqual(row['buckets']['not_due'], 100.0, places=2)
        self.assertAlmostEqual(row['buckets']['b31_60'], 200.0, places=2)
        self.assertAlmostEqual(row['total'], 300.0, places=2)

    def test_bucket_totals_sum_to_grand_total(self):
        data = self.receivable_report.action_get_report_data({'date_to': '2025-03-01'})
        row = next(r for r in data['lines'] if r['partner_id'] == self.partner_a.id)
        self.assertAlmostEqual(sum(row['buckets'].values()), row['total'], places=2)

    def test_payable_shows_positive_amount_owed(self):
        """Payable residuals are credit-normal (negative raw balance); the
        report must negate them so 'amount we owe' reads positive."""
        data = self.payable_report.action_get_report_data({'date_to': '2025-03-01'})
        row = next(r for r in data['lines'] if r['partner_id'] == self.partner_b.id)
        self.assertGreater(row['total'], 0.0)
        self.assertAlmostEqual(row['total'], 150.0, places=2)

    def test_focus_partner_filters_to_single_partner(self):
        data = self.receivable_report.action_get_report_data({
            'date_to': '2025-03-01', 'focus_partner_id': self.partner_a.id,
        })
        self.assertEqual(len(data['lines']), 1)
        self.assertEqual(data['lines'][0]['partner_id'], self.partner_a.id)

    def test_expanded_row_lists_open_items_with_due_dates(self):
        data = self.receivable_report.action_get_report_data({
            'date_to': '2025-03-01', 'unfolded_line_ids': [self.partner_a.id],
        })
        row = next(r for r in data['lines'] if r['partner_id'] == self.partner_a.id)
        self.assertEqual(len(row['aml_rows']), 2)
        due_dates = {r['due_date'] for r in row['aml_rows']}
        self.assertEqual(due_dates, {'2025-04-15', '2025-01-15'})

    def test_many_open_items_paginate_via_load_more(self):
        """Aged Balance sorts its "Load more" cursor by (date_maturity,
        date, id) rather than the plain (date, id) every other handler
        uses - due date is what actually matters for an aging report - so
        this needs its own dedicated pagination test rather than trusting
        the General Ledger one to cover it. Bucket totals must also stay
        correct for the *entire* set of open items regardless of how many
        pages have been fetched, since they're computed once up front, not
        accumulated page by page."""
        from odoo.addons.account_reports_community_v2.models.account_report_engine import AML_PAGE_SIZE

        journal = self.company_data['default_journal_misc']
        extra_count = AML_PAGE_SIZE + 15
        for i in range(extra_count):
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': journal.id,
                'date': '2025-02-01',
                'line_ids': [
                    (0, 0, {
                        'account_id': self.receivable_account.id, 'partner_id': self.partner_a.id,
                        'debit': 10.0, 'credit': 0.0, 'date_maturity': f'2025-02-{(i % 27) + 1:02d}',
                    }),
                    (0, 0, {'account_id': self.revenue_account.id, 'debit': 0.0, 'credit': 10.0}),
                ],
            })
            move.action_post()

        data = self.receivable_report.action_get_report_data({
            'date_to': '2025-03-01', 'unfolded_line_ids': [self.partner_a.id],
        })
        row = next(r for r in data['lines'] if r['partner_id'] == self.partner_a.id)
        self.assertEqual(len(row['aml_rows']), AML_PAGE_SIZE)
        self.assertTrue(row['aml_rows_has_more'])
        # Bucket totals cover every open item (2 from setUpClass + extra_count),
        # not just the first page sent to the browser.
        self.assertAlmostEqual(sum(row['buckets'].values()), 300.0 + extra_count * 10.0, places=2)

        last_row = row['aml_rows'][-1]
        more = self.receivable_report.action_get_more_aml_rows(
            options={'date_to': '2025-03-01'},
            group_id=self.partner_a.id,
            after_id=last_row['id'],
            after_date=last_row['date'],
            after_maturity=last_row['due_date'],
        )
        # 2 original items + extra_count new ones, minus the first page already fetched.
        self.assertEqual(len(more['aml_rows']), 2 + extra_count - AML_PAGE_SIZE)
        self.assertFalse(more['aml_rows_has_more'])
        seen_ids = {r['id'] for r in row['aml_rows']} | {r['id'] for r in more['aml_rows']}
        self.assertEqual(len(seen_ids), 2 + extra_count, "Load more must not skip or repeat any row")
