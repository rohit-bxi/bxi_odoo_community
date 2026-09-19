from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestJournalReport(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env.ref('account_reports_community_v2.journal_report_community')
        cls.expense_account = cls.company_data['default_account_expense']
        cls.revenue_account = cls.company_data['default_account_revenue']
        cls.journal = cls.company_data['default_journal_misc']

        cls.move = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': cls.journal.id,
            'date': '2025-01-15',
            'line_ids': [
                (0, 0, {'account_id': cls.expense_account.id, 'debit': 100.0, 'credit': 0.0}),
                (0, 0, {'account_id': cls.revenue_account.id, 'debit': 0.0, 'credit': 100.0}),
            ],
        })
        cls.move.action_post()

    def _get_data(self, **kwargs):
        options = {'date_from': '2025-01-01', 'date_to': '2025-03-01'}
        options.update(kwargs)
        return self.report.action_get_report_data(options)

    def test_journal_totals_debit_and_credit(self):
        data = self._get_data()
        row = next(r for r in data['lines'] if r['journal_id'] == self.journal.id)
        self.assertAlmostEqual(row['total_debit'], 100.0, places=2)
        self.assertAlmostEqual(row['total_credit'], 100.0, places=2)

    def test_unfolded_row_lists_journal_items(self):
        data = self._get_data(unfolded_line_ids=[self.journal.id])
        row = next(r for r in data['lines'] if r['journal_id'] == self.journal.id)
        self.assertEqual(len(row['aml_rows']), 2)

    def test_empty_journal_not_shown(self):
        other_journal = self.env['account.journal'].create({
            'name': 'Empty Journal',
            'type': 'general',
            'code': 'EMPJ',
            'company_id': self.env.company.id,
        })
        data = self._get_data()
        journal_ids = {r['journal_id'] for r in data['lines']}
        self.assertNotIn(other_journal.id, journal_ids)
