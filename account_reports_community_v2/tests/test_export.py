import io

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged

from odoo.addons.account_reports_community_v2.report.xlsx_export import build_xlsx

# Every report shipped by this module, one xmlid per report_handler so a
# single regression here catches a broken assumption in any of the bespoke
# handlers' data shape, not just the generic hierarchy one.
REPORT_XMLIDS = [
    'account_reports_community_v2.trial_balance_report',
    'account_reports_community_v2.general_ledger_report',
    'account_reports_community_v2.partner_ledger_report',
    'account_reports_community_v2.aged_receivable_report',
    'account_reports_community_v2.tax_report_community',
    'account_reports_community_v2.journal_report_community',
]


@tagged('post_install', '-at_install')
class TestExport(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        revenue_account = cls.company_data['default_account_revenue']
        receivable_account = cls.company_data['default_account_receivable']
        journal = cls.company_data['default_journal_misc']

        move = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'partner_id': cls.partner_a.id,
            'date': '2025-01-15',
            'line_ids': [
                (0, 0, {'account_id': receivable_account.id, 'partner_id': cls.partner_a.id, 'debit': 100.0, 'credit': 0.0}),
                (0, 0, {'account_id': revenue_account.id, 'debit': 0.0, 'credit': 100.0}),
            ],
        })
        move.action_post()

        # A real invoice with a tax line, so tax_report (which only groups
        # move lines that actually carry a tax_line_id) has something to show.
        invoice = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': cls.partner_a.id,
            'invoice_date': '2025-01-20',
            'invoice_line_ids': [
                (0, 0, {'name': "Test line", 'quantity': 1, 'price_unit': 200.0, 'tax_ids': [(6, 0, cls.tax_sale_a.ids)]}),
            ],
        })
        invoice.action_post()

    def _export_data(self, report):
        options = report._get_default_options({
            'date_from': '2025-01-01', 'date_to': '2025-03-01', 'export_mode': True,
        })
        return report._get_report_data(options)

    def test_xlsx_export_builds_readable_workbook_for_every_report(self):
        import openpyxl  # noqa: PLC0415

        for xmlid in REPORT_XMLIDS:
            report = self.env.ref(xmlid)
            data = self._export_data(report)
            xlsx_bytes = build_xlsx(report, data)
            self.assertTrue(xlsx_bytes, f"{xmlid}: XLSX export produced no bytes")

            workbook = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
            sheet = workbook.active
            self.assertGreater(sheet.max_row, 1, f"{xmlid}: XLSX export has no data rows")

    def test_pdf_export_renders_non_empty_content_for_every_report(self):
        """The PDF action's QWeb template must render real content for
        every report.

        This deliberately does NOT force a real wkhtmltopdf call (there's
        no `force_report_rendering` context override here): wkhtmltopdf
        needs to fetch the rendered page back from this same Odoo process
        over HTTP, which deadlocks under the single-process/no-extra-
        workers server every `--test-enable` run uses - that's exactly why
        Odoo core's `_pre_render_qweb_pdf` unconditionally falls back to
        plain HTML whenever `test_enable`/`current_test` is set, regardless
        of whether wkhtmltopdf is installed. Forcing it here would hang the
        test suite rather than test anything. Asserting on the HTML
        fallback's content instead still catches the actual class of bug
        this test cares about (a broken QWeb template, a key the template
        expects but the data dict doesn't provide), without needing a real
        wkhtmltopdf round-trip.
        """
        for xmlid in REPORT_XMLIDS:
            report = self.env.ref(xmlid)
            data = self._export_data(report)
            content, report_type = self.env['ir.actions.report']._render_qweb_pdf(
                'account_reports_community_v2.account_report_pdf_action',
                res_ids=None,
                data={'report_data': data},
            )
            self.assertEqual(report_type, 'html')
            self.assertGreater(len(content), 1000, f"{xmlid}: rendered report looks empty/truncated")
            self.assertIn(b'<table', content, f"{xmlid}: rendered report doesn't contain the report table")
