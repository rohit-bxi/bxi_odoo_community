import json

from odoo import http
from odoo.http import content_disposition, request
from odoo.tools import osutil

from ..report.xlsx_export import build_xlsx

PDF_REPORT_XMLID = 'account_reports_community_v2.account_report_pdf_action'


class AccountReportsCommunityController(http.Controller):

    def _get_export_data(self, report_id, options):
        """Shared by both export routes: resolves the report + options exactly
        like action_get_report_data does, but always forcing export_mode so
        every foldable row is expanded and no aml_rows list is capped -
        an export is supposed to contain everything, not whatever happens to
        be folded/capped in the browser right now."""
        report = request.env['account.report'].browse(int(report_id))
        params = json.loads(options) if options else {}
        params['export_mode'] = True
        resolved_options = report._get_default_options(params)
        data = report._get_report_data(resolved_options)
        return report, data

    @http.route('/account_reports_community_v2/xlsx', type='http', auth='user', methods=['POST'], readonly=True)
    def export_xlsx(self, report_id, options=None, **kwargs):
        report, data = self._get_export_data(report_id, options)
        xlsx_data = build_xlsx(report, data)
        filename = osutil.clean_filename(report.name) + '.xlsx'
        return request.make_response(
            xlsx_data,
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', content_disposition(filename)),
            ],
        )

    @http.route('/account_reports_community_v2/pdf', type='http', auth='user', methods=['POST'])
    def export_pdf(self, report_id, options=None, **kwargs):
        report, data = self._get_export_data(report_id, options)
        pdf_content, _report_type = request.env['ir.actions.report']._render_qweb_pdf(
            PDF_REPORT_XMLID, res_ids=None, data={'report_data': data},
        )
        filename = osutil.clean_filename(report.name) + '.pdf'
        return request.make_response(
            pdf_content,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', content_disposition(filename)),
            ],
        )
