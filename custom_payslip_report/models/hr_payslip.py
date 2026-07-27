from odoo import models, fields, api, _

class HrPayslip(models.Model):
    _inherit = 'hr.payslip'


    def action_print_custom_payslip(self):
        self.ensure_one()
        xmlid = "custom_payslip_report.action_custom_payslip_pdf"
        try:
            report = self.env.ref(xmlid)
        except ValueError:
            raise UserError(_(
                "Report Not Fount"))
        return report.report_action(self)


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