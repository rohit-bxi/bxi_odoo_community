# -*- coding: utf-8 -*-
from odoo import models


class TdsReportWizard(models.TransientModel):
    _name = 'tds.report.wizard'
    _inherit = 'bxi.payroll.report.mixin'
    _description = 'TDS (Employee) Report Wizard'

    def action_generate_excel(self):
        self.ensure_one()
        start_date, end_date, period_label, file_period, period_type_label = self._get_period_bounds()
        payslips = self._get_period_payslips(start_date, end_date, period_label)

        total_tds = 0.0
        for slip in payslips:
            if not slip.employee_id:
                continue
            for line in self._get_payslip_lines(slip):
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
                    total_tds += amount_val

        return self._build_summary_excel(
            sheet_name='TDS Report',
            title=f"TDS (EMPLOYEE) REPORT - {self.company_id.name}",
            subtitle=f"Period Type: {period_type_label} | Period: {period_label}",
            headers=['Period', 'Total TDS Amount'],
            row_values=[period_label, total_tds],
            col_widths=[26, 22],
            file_name=f"TDS_Report_{file_period}.xlsx",
        )
