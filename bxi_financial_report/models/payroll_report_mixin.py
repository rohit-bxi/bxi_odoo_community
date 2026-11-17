# -*- coding: utf-8 -*-
import io
import base64
import calendar
from datetime import date
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import xlsxwriter


class BxiPayrollReportMixin(models.AbstractModel):
    _name = 'bxi.payroll.report.mixin'
    _description = 'Payroll Report Wizard Mixin'

    @api.model
    def _get_period_type_selection(self):
        return [
            ('yearly', 'Yearly'),
            ('quarterly', 'Quarterly'),
            ('monthly', 'Monthly'),
        ]

    @api.model
    def _get_quarter_selection(self):
        return [
            ('q1', 'Q1 (Jan - Mar)'),
            ('q2', 'Q2 (Apr - Jun)'),
            ('q3', 'Q3 (Jul - Sep)'),
            ('q4', 'Q4 (Oct - Dec)'),
        ]

    @api.model
    def _get_month_selection(self):
        return [
            ('1', 'January'),
            ('2', 'February'),
            ('3', 'March'),
            ('4', 'April'),
            ('5', 'May'),
            ('6', 'June'),
            ('7', 'July'),
            ('8', 'August'),
            ('9', 'September'),
            ('10', 'October'),
            ('11', 'November'),
            ('12', 'December'),
        ]

    @api.model
    def _get_year_selection(self):
        current_year = date.today().year
        return [(str(y), str(y)) for y in range(2020, current_year + 6)]

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        domain="[('id', 'in', allowed_company_ids)]"
    )
    period_type = fields.Selection(
        selection='_get_period_type_selection',
        string='Period Type',
        required=True,
        default='monthly'
    )
    year = fields.Selection(
        selection='_get_year_selection',
        string='Year',
        required=True,
        default=lambda self: str(date.today().year)
    )
    quarter = fields.Selection(
        selection='_get_quarter_selection',
        string='Quarter',
        default='q1'
    )
    month = fields.Selection(
        selection='_get_month_selection',
        string='Month',
        default=lambda self: str(date.today().month)
    )

    def _get_period_bounds(self):
        """Return (start_date, end_date, period_label, file_period, period_type_label)."""
        self.ensure_one()
        if not self.year:
            raise UserError(_("Please select a Year."))
        year_int = int(self.year)
        period_type_label = dict(self._get_period_type_selection()).get(self.period_type, '')

        if self.period_type == 'yearly':
            start_date = date(year_int, 1, 1)
            end_date = date(year_int, 12, 31)
            period_label = str(self.year)
            file_period = f"Yearly_{self.year}"
        elif self.period_type == 'quarterly':
            q_ranges = {'q1': (1, 3), 'q2': (4, 6), 'q3': (7, 9), 'q4': (10, 12)}
            if self.quarter not in q_ranges:
                raise UserError(_("Please select a Quarter."))
            m_start, m_end = q_ranges[self.quarter]
            start_date = date(year_int, m_start, 1)
            end_date = date(year_int, m_end, calendar.monthrange(year_int, m_end)[1])
            q_label = dict(self._get_quarter_selection()).get(self.quarter, self.quarter.upper())
            period_label = f"{q_label} {self.year}"
            file_period = f"{self.quarter.upper()}_{self.year}"
        else:
            if not self.month:
                raise UserError(_("Please select a Month."))
            month_int = int(self.month)
            last_day = calendar.monthrange(year_int, month_int)[1]
            start_date = date(year_int, month_int, 1)
            end_date = date(year_int, month_int, last_day)
            month_name = dict(self._get_month_selection()).get(self.month, '')
            period_label = f"{month_name} {self.year}"
            file_period = f"{month_name}_{self.year}"

        return start_date, end_date, period_label, file_period, period_type_label

    def _get_period_payslips(self, start_date, end_date, period_label):
        """Fetch non-cancelled payslips overlapping [start_date, end_date] for the selected company."""
        if 'hr.payslip' not in self.env:
            raise UserError(_("Payroll module (hr.payslip) is not installed in the system."))

        payslip_domain = [
            ('state', '!=', 'cancel'),
            ('date_from', '<=', end_date.strftime('%Y-%m-%d')),
            ('date_to', '>=', start_date.strftime('%Y-%m-%d')),
        ]
        if self.company_id:
            payslip_domain.append(('company_id', '=', self.company_id.id))

        payslips = self.env['hr.payslip'].sudo().search(payslip_domain)
        if not payslips:
            raise UserError(_(
                "No payslips found for period %s for %s. Please ensure payslips exist for the selected period."
            ) % (period_label, self.company_id.name))
        return payslips

    def _get_payslip_lines(self, slip):
        lines = slip.line_ids
        if not lines and 'hr.payslip.line' in self.env:
            lines = self.env['hr.payslip.line'].sudo().search([('slip_id', '=', slip.id)])
        return lines

    def _build_summary_excel(self, sheet_name, title, subtitle, headers, row_values, col_widths, file_name):
        """Generate a single-row total summary Excel workbook and return an act_url download action."""
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet(sheet_name)

        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#0F172A',
            'font_color': '#FFFFFF',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
        })
        title_format = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'align': 'left',
            'valign': 'vcenter',
        })
        subtitle_format = workbook.add_format({
            'italic': True,
            'font_size': 10,
            'font_color': '#64748B',
        })
        total_label_format = workbook.add_format({
            'bold': True,
            'bg_color': '#E2E8F0',
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
        })
        total_amount_format = workbook.add_format({
            'bold': True,
            'num_format': '#,##0.00',
            'bg_color': '#E2E8F0',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
        })

        worksheet.write(0, 0, title, title_format)
        worksheet.write(1, 0, subtitle, subtitle_format)

        for col_num, header_title in enumerate(headers):
            worksheet.write(3, col_num, header_title, header_format)
        worksheet.set_row(3, 26)

        for col_num, val in enumerate(row_values):
            cell_fmt = total_label_format if isinstance(val, str) else total_amount_format
            worksheet.write(4, col_num, val, cell_fmt)
        worksheet.set_row(4, 22)

        for col_num, width in enumerate(col_widths):
            worksheet.set_column(col_num, col_num, width)

        workbook.close()
        output.seek(0)

        attachment = self.env['ir.attachment'].create({
            'name': file_name,
            'type': 'binary',
            'datas': base64.b64encode(output.getvalue()),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

