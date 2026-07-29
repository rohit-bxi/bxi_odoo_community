from odoo import models, fields, api, _
from odoo.exceptions import UserError

class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    @api.model
    def _register_hook(self):
        res = super()._register_hook()
        try:
            # Auto-fix legacy enterprise salary rules in database table hr_salary_rule
            self.env.cr.execute("""
                UPDATE hr_salary_rule
                SET amount_python_compute = 'result = -round((employee.l10n_in_basic_salary_amount or contract.wage or 0.0) * 0.12, 2)'
                WHERE amount_python_compute LIKE '%version.pf_employee_amount%';
            """)
            self.env.cr.execute("""
                UPDATE hr_salary_rule
                SET amount_python_compute = REPLACE(amount_python_compute, 'version.', 'contract.')
                WHERE amount_python_compute LIKE '%version.%';
            """)
            self.env.cr.commit()
        except Exception:
            pass
        return res

    @api.onchange('struct_id')
    def _onchange_struct_id_inputs(self):
        if not self.struct_id:
            return
        rules = self.struct_id.get_all_rules()
        rule_ids = [r[0] for r in rules]
        input_objs = self.env['hr.salary.rule'].browse(rule_ids).mapped('input_ids')

        existing_codes = self.input_line_ids.mapped('code')
        new_lines = []
        for inp in input_objs:
            if inp.code not in existing_codes:
                new_lines.append((0, 0, {
                    'name': inp.name,
                    'code': inp.code,
                    'amount': 0.0,
                }))
        if new_lines:
            self.input_line_ids = new_lines

    def action_print_custom_payslip(self):
        self.ensure_one()
        xmlid = "custom_payslip_report.action_custom_payslip_pdf"
        try:
            report = self.env.ref(xmlid)
        except ValueError:
            raise UserError(_("Report Not Found"))
        return report.report_action(self)

    def compute_sheet(self):
        # 1. Ensure any legacy rules with version. references are cleaned up prior to computation
        rules = self.env['hr.salary.rule'].sudo().search([
            ('amount_python_compute', 'like', 'version.')
        ])
        for rule in rules:
            code = rule.amount_python_compute or ''
            if 'pf_employee_amount' in code:
                rule.sudo().write({
                    'amount_python_compute': 'result = -round((employee.l10n_in_basic_salary_amount or contract.wage or 0.0) * 0.12, 2)'
                })
            else:
                new_code = code.replace('version.', 'contract.')
                rule.sudo().write({'amount_python_compute': new_code})

        # 2. Ensure all input lines from the structure's rules are present on the payslip
        for payslip in self:
            if payslip.struct_id:
                struct_rules = payslip.struct_id.get_all_rules()
                rule_ids = [r[0] for r in struct_rules]
                input_objs = self.env['hr.salary.rule'].browse(rule_ids).mapped('input_ids')
                existing_codes = payslip.input_line_ids.mapped('code')
                
                missing_inputs = []
                for inp in input_objs:
                    if inp.code not in existing_codes:
                        missing_inputs.append((0, 0, {
                            'name': inp.name,
                            'code': inp.code,
                            'amount': 0.0,
                        }))
                if missing_inputs:
                    payslip.write({'input_line_ids': missing_inputs})

        return super().compute_sheet()


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    @api.model
    def _action_create_monthly_runs(self):
        from datetime import date
        import calendar

        today = date.today()
        last_day = calendar.monthrange(today.year, today.month)[1]

        # Only execute on the last day of the month
        if today.day != last_day:
            return

        start_date = today.replace(day=1)
        end_date = today.replace(day=last_day)

        month_name = today.strftime('%B')
        year_str = today.strftime('%Y')

        companies = self.env['res.company'].search([])
        for company in companies:
            existing = self.search([
                ('company_id', '=', company.id),
                ('date_start', '=', start_date),
                ('date_end', '=', end_date)
            ])
            if not existing:
                run_name = f"Payslip Run - {month_name} {year_str} - {company.name}"
                new_run = self.create({
                    'name': run_name,
                    'company_id': company.id,
                    'date_start': start_date,
                    'date_end': end_date,
                    'state': '01_ready'
                })
                employees = self.env['hr.employee'].search([('company_id', '=', company.id)])
                if employees:
                    try:
                        version_ids = new_run._get_valid_version_ids(employee_ids=employees.ids)
                        if version_ids:
                            new_run.generate_payslips(version_ids=version_ids)
                    except Exception as e:
                        pass