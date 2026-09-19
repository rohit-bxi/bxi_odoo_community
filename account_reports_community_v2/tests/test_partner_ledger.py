from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestPartnerLedger(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env.ref('account_reports_community_v2.partner_ledger_report')
        cls.receivable_account = cls.company_data['default_account_receivable']
        cls.revenue_account = cls.company_data['default_account_revenue']
        journal = cls.company_data['default_journal_misc']

        cls.move_1 = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': '2025-01-15',
            'line_ids': [
                (0, 0, {
                    'account_id': cls.receivable_account.id, 'partner_id': cls.partner_a.id,
                    'debit': 100.0, 'credit': 0.0,
                }),
                (0, 0, {'account_id': cls.revenue_account.id, 'debit': 0.0, 'credit': 100.0}),
            ],
        })
        cls.move_1.action_post()

        cls.move_2 = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': '2025-02-15',
            'line_ids': [
                (0, 0, {
                    'account_id': cls.receivable_account.id, 'partner_id': cls.partner_a.id,
                    'debit': 50.0, 'credit': 0.0,
                }),
                (0, 0, {'account_id': cls.revenue_account.id, 'debit': 0.0, 'credit': 50.0}),
            ],
        })
        cls.move_2.action_post()

    def _get_data(self, date_from, date_to, focus_partner_id=None):
        options = {'date_from': date_from, 'date_to': date_to}
        if focus_partner_id:
            options['focus_partner_id'] = focus_partner_id
            # Mirrors what the frontend does when a user expands a partner
            # row: aml_rows are only populated for unfolded partners.
            options['unfolded_line_ids'] = [focus_partner_id]
        return self.report.action_get_report_data(options)

    def test_opening_plus_movement_equals_closing(self):
        data = self._get_data('2025-01-01', '2025-03-01', focus_partner_id=self.partner_a.id)
        row = data['lines'][0]
        total_debit = sum(r['debit'] for r in row['aml_rows'])
        total_credit = sum(r['credit'] for r in row['aml_rows'])
        self.assertAlmostEqual(
            row['opening_balance'] + total_debit - total_credit, row['closing_balance'], places=2,
        )

    def test_running_balance_matches_final_closing(self):
        data = self._get_data('2025-01-01', '2025-03-01', focus_partner_id=self.partner_a.id)
        row = data['lines'][0]
        self.assertTrue(row['aml_rows'], "Expected journal items for the partner")
        self.assertAlmostEqual(row['aml_rows'][-1]['running_balance'], row['closing_balance'], places=2)

    def test_focus_partner_filters_to_single_partner(self):
        data = self._get_data('2025-01-01', '2025-03-01', focus_partner_id=self.partner_a.id)
        self.assertEqual(len(data['lines']), 1)
        self.assertEqual(data['lines'][0]['partner_id'], self.partner_a.id)

    def test_closing_balance_matches_receivable_movement(self):
        """Only the receivable-account side of the postings should count
        (100 + 50 = 150), not the revenue side, which carries no partner_id."""
        data = self._get_data('2025-01-01', '2025-03-01', focus_partner_id=self.partner_a.id)
        self.assertAlmostEqual(data['lines'][0]['closing_balance'], 150.0, places=2)

    def test_period_continuity(self):
        """Closing balance of period 1 must equal opening balance of period 2."""
        period_1 = self._get_data('2025-01-01', '2025-01-31', focus_partner_id=self.partner_a.id)
        period_2 = self._get_data('2025-02-01', '2025-02-28', focus_partner_id=self.partner_a.id)
        self.assertAlmostEqual(
            period_1['lines'][0]['closing_balance'], period_2['lines'][0]['opening_balance'], places=2,
        )

    def test_partner_ids_filter_excludes_other_partners(self):
        """Filtering to a partner with no receivable/payable movement of
        their own must show no rows at all."""
        data = self.report.action_get_report_data({
            'date_from': '2025-01-01', 'date_to': '2025-03-01',
            'partner_ids': [self.partner_b.id],
        })
        self.assertFalse(data['lines'])

    def test_available_partners_includes_only_receivable_payable_partners(self):
        partners = self.report.action_get_available_partners()
        partner_ids = {p['id'] for p in partners}
        self.assertIn(self.partner_a.id, partner_ids)
