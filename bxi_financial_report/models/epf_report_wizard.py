# -*- coding: utf-8 -*-
from odoo import models


class EpfReportWizard(models.TransientModel):
    _name = 'epf.report.wizard'
    _inherit = 'bxi.payroll.report.mixin'
    _description = 'EPF Report Wizard'

    def action_generate_excel(self):
        self.ensure_one()
        start_date, end_date, period_label, file_period, period_type_label = self._get_period_bounds()
        payslips = self._get_period_payslips(start_date, end_date, period_label)

        total_emp_pf = 0.0
        for slip in payslips:
            if not slip.employee_id:
                continue
            for line in self._get_payslip_lines(slip):
                code_upper = (line.code or '').upper().strip()
                name_upper = (line.name or '').upper().strip()
                cat_code = (line.category_id.code if line.category_id else '').upper().strip()
                cat_name = (line.category_id.name if line.category_id else '').upper().strip()

                is_pf = False
                if code_upper in ('PF', 'EPF', 'PF_EMP', 'EMPLOYEE_PF', 'EPF_EMP', 'PF_EMPLOYEE', 'PF_DED'):
                    is_pf = True
                elif 'PROVIDENT' in name_upper or 'PROVIDENT' in code_upper:
                    is_pf = True
                elif 'PF' in code_upper or 'PF' in name_upper or 'EPF' in code_upper or 'EPF' in name_upper:
                    is_pf = True
                elif any(k in cat_code for k in ('DED', 'DEDUCTION')) and any(k in code_upper or k in name_upper for k in ('PF', 'EPF', 'PROVIDENT')):
                    is_pf = True
                elif any(k in cat_name for k in ('DED', 'DEDUCTION')) and any(k in code_upper or k in name_upper for k in ('PF', 'EPF', 'PROVIDENT')):
                    is_pf = True

                if is_pf:
                    amount_val = abs(line.total if (hasattr(line, 'total') and line.total != 0) else (getattr(line, 'amount', 0.0) or 0.0))
                    total_emp_pf += amount_val

        total_employer_pf = total_emp_pf
        total_pf = total_emp_pf + total_employer_pf

        return self._build_summary_excel(
            sheet_name='EPF Report',
            title=f"EPF REPORT - {self.company_id.name}",
            subtitle=f"Period Type: {period_type_label} | Period: {period_label}",
            headers=['Period', 'Total Employee PF', 'Total Employer PF', 'Total PF'],
            row_values=[period_label, total_emp_pf, total_employer_pf, total_pf],
            col_widths=[26, 20, 20, 18],
            file_name=f"EPF_Report_{file_period}.xlsx",
        )
