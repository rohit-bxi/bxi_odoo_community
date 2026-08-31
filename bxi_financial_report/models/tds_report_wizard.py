# -*- coding: utf-8 -*-
import io
import base64
import calendar
from datetime import date
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import xlsxwriter

class TdsReportWizard(models.TransientModel):
    _name = 'tds.report.wizard'
    _description = 'TDS (Employee) Report Wizard'

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

    month = fields.Selection(
        selection='_get_month_selection',
        string='Month',
        required=True,
        default=lambda self: str(date.today().month)
    )
    year = fields.Selection(
        selection='_get_year_selection',
        string='Year',
        required=True,
        default=lambda self: str(date.today().year)
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        domain="[('id', 'in', allowed_company_ids)]"
    )

    def action_generate_excel(self):
        self.ensure_one()

        year_int = int(self.year)
        month_int = int(self.month)
        last_day = calendar.monthrange(year_int, month_int)[1]
        start_date = date(year_int, month_int, 1)
        end_date = date(year_int, month_int, last_day)

        if 'hr.payslip' not in self.env:
            raise UserError(_("Payroll module (hr.payslip) is not installed in the system."))

        start_dt_str = start_date.strftime('%Y-%m-%d')
        end_dt_str = end_date.strftime('%Y-%m-%d')

        # Search payslips matching the selected pay period and selected company
        payslip_domain = [
            ('state', '!=', 'cancel'),
            ('date_from', '<=', end_dt_str),
            ('date_to', '>=', start_dt_str),
        ]
        if self.company_id:
            payslip_domain.append(('company_id', '=', self.company_id.id))

        payslips = self.env['hr.payslip'].sudo().search(payslip_domain)

        month_name = dict(self._get_month_selection()).get(self.month, '')
        if not payslips:
            raise UserError(_("No payslips found for period %s %s for %s. Please ensure payslips exist for the selected month and year.") % (month_name, self.year, self.company_id.name))

        # Map data per employee
        employee_data = {}
        for slip in payslips:
            emp = slip.employee_id
            if not emp:
                continue

            emp_key = emp.id
            if emp_key not in employee_data:
                # Resolve Employee Code from hr.employee
                emp_code = ''
                for code_field in ('employee_code', 'registration_number', 'emp_code', 'barcode', 'identification_id'):
                    if hasattr(emp, code_field) and getattr(emp, code_field):
                        emp_code = str(getattr(emp, code_field))
                        break
                if not emp_code:
                    emp_code = str(emp.id)

                # Resolve PAN Number
                pan_no = ''
                for pan_field in ('l10n_in_pan', 'pan_no', 'pan_number', 'pan'):
                    if hasattr(emp, pan_field) and getattr(emp, pan_field):
                        pan_no = str(getattr(emp, pan_field))
                        break

                employee_data[emp_key] = {
                    'emp_code': emp_code,
                    'emp_name': emp.name or '',
                    'pan_no': pan_no,
                    'tds_amount': 0.0,
                }

            # Find TDS contribution in payslip lines
            lines = slip.line_ids
            if not lines and 'hr.payslip.line' in self.env:
                lines = self.env['hr.payslip.line'].sudo().search([('slip_id', '=', slip.id)])

            for line in lines:
                code_upper = (line.code or '').upper().strip()
                name_upper = (line.name or '').upper().strip()
                cat_code = (line.category_id.code if line.category_id else '').upper().strip()
                cat_name = (line.category_id.name if line.category_id else '').upper().strip()

                is_tds = False
                if code_upper in ('TDS', 'TDS_EMP', 'TDS_DED', 'INCOME_TAX', 'TAX', 'IT', 'TDS_EMPLOYEE'):
                    is_tds = True
                elif 'TDS' in code_upper or 'INCOME TAX' in name_upper or 'TAX DEDUCTED' in name_upper or 'TDS' in name_upper:
                    is_tds = True
                elif any(k in cat_code for k in ('DED', 'DEDUCTION')) and ('TDS' in code_upper or 'TDS' in name_upper or 'TAX' in name_upper):
                    is_tds = True
                elif any(k in cat_name for k in ('DED', 'DEDUCTION')) and ('TDS' in code_upper or 'TDS' in name_upper or 'TAX' in name_upper):
                    is_tds = True

                if is_tds:
                    amount_val = abs(line.total if (hasattr(line, 'total') and line.total != 0) else (getattr(line, 'amount', 0.0) or 0.0))
                    employee_data[emp_key]['tds_amount'] += amount_val

        # Create Excel workbook in memory
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('TDS Report')

        # Formatting Styles
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#0F172A',
            'font_color': '#FFFFFF',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1
        })
        title_format = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'align': 'left',
            'valign': 'vcenter'
        })
        subtitle_format = workbook.add_format({
            'italic': True,
            'font_size': 10,
            'font_color': '#64748B'
        })
        data_format = workbook.add_format({
            'align': 'left',
            'valign': 'vcenter',
            'border': 1
        })
        amount_format = workbook.add_format({
            'num_format': '#,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1
        })
        total_header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#E2E8F0',
            'align': 'left',
            'valign': 'vcenter',
            'border': 1
        })
        total_amount_format = workbook.add_format({
            'bold': True,
            'num_format': '#,##0.00',
            'bg_color': '#E2E8F0',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1
        })

        # Write Title Header
        worksheet.write(0, 0, f"TDS (EMPLOYEE) REPORT - {self.company_id.name}", title_format)
        worksheet.write(1, 0, f"Period: {month_name} {self.year}", subtitle_format)

        # Write Table Column Headers (Row 3)
        headers = ['Employee Code', 'Employee Name', 'PAN Number', 'TDS Amount']
        for col_num, header_title in enumerate(headers):
            worksheet.write(3, col_num, header_title, header_format)

        worksheet.set_row(3, 26)

        row_num = 4
        total_tds = 0.0

        # Sort employees by code/name
        sorted_emp_keys = sorted(employee_data.keys(), key=lambda k: (employee_data[k]['emp_code'], employee_data[k]['emp_name']))

        for emp_key in sorted_emp_keys:
            emp_info = employee_data[emp_key]
            tds_amt = emp_info['tds_amount']

            # Include only records whose tax is deducted
            if tds_amt <= 0:
                continue

            worksheet.write(row_num, 0, emp_info['emp_code'], data_format)
            worksheet.write(row_num, 1, emp_info['emp_name'], data_format)
            worksheet.write(row_num, 2, emp_info['pan_no'], data_format)
            worksheet.write(row_num, 3, tds_amt, amount_format)

            total_tds += tds_amt
            row_num += 1

        # Write Total Row
        worksheet.write(row_num, 0, 'Total', total_header_format)
        worksheet.write(row_num, 1, '', total_header_format)
        worksheet.write(row_num, 2, '', total_header_format)
        worksheet.write(row_num, 3, total_tds, total_amount_format)

        # Set Column Widths
        worksheet.set_column(0, 0, 18)
        worksheet.set_column(1, 1, 30)
        worksheet.set_column(2, 2, 20)
        worksheet.set_column(3, 3, 18)

        workbook.close()
        output.seek(0)

        # Create Attachment & Return Download Action
        file_name = f"TDS_Report_{month_name}_{self.year}.xlsx"
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
