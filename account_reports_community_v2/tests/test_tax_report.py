from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestTaxReport(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env.ref('account_reports_community_v2.tax_report_community')

        cls.sale_tax = cls.env['account.tax'].create({
            'name': 'Test Sale Tax 15%',
            'amount': 15.0,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
        })

        cls.invoice = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': cls.partner_a.id,
            'invoice_date': '2025-01-20',
            'invoice_line_ids': [(0, 0, {
                'product_id': cls.product_a.id,
                'quantity': 1,
                'price_unit': 1000.0,
                'tax_ids': [(6, 0, cls.sale_tax.ids)],
            })],
        })
        cls.invoice.action_post()

    def _get_data(self, **kwargs):
        options = {'date_from': '2025-01-01', 'date_to': '2025-03-01'}
        options.update(kwargs)
        return self.report.action_get_report_data(options)

    def test_sale_tax_shows_base_and_tax_amount(self):
        data = self._get_data()
        row = next(r for r in data['lines'] if r['tax_id'] == self.sale_tax.id)
        self.assertEqual(row['tax_type'], 'sale')
        self.assertAlmostEqual(row['base_amount'], 1000.0, places=2)
        self.assertAlmostEqual(row['tax_amount'], 150.0, places=2)

    def test_unfolded_row_lists_journal_items(self):
        data = self._get_data(unfolded_line_ids=[self.sale_tax.id])
        row = next(r for r in data['lines'] if r['tax_id'] == self.sale_tax.id)
        self.assertTrue(row['aml_rows'])
        self.assertAlmostEqual(row['aml_rows'][0]['tax_amount'], 150.0, places=2)

    def test_folded_row_has_no_journal_items(self):
        data = self._get_data()
        row = next(r for r in data['lines'] if r['tax_id'] == self.sale_tax.id)
        self.assertFalse(row['unfolded'])
        self.assertEqual(row['aml_rows'], [])
