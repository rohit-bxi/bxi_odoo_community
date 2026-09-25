from odoo import models
from odoo.exceptions import UserError


class HrPayslipEmployees(models.TransientModel):
    _inherit = 'hr.payslip.employees'

    def compute_sheet(self):
        """Leave out employees who are on a host payroll for the whole batch period."""
        run_id = self.env.context.get('active_id')
        if run_id:
            run = self.env['hr.payslip.run'].browse(run_id)
            date_from, date_to = run.date_start, run.date_end
            period_days = (date_to - date_from).days + 1
            on_host_payroll = self.employee_ids.filtered(
                lambda e: e._get_off_home_payroll_days(date_from, date_to) >= period_days)
            if on_host_payroll:
                self.employee_ids -= on_host_payroll
                if not self.employee_ids:
                    raise UserError(self.env._(
                        'All selected employees are on a host country payroll for this period.'))
        return super().compute_sheet()
