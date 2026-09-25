from odoo import models

from odoo.addons.bxi_salary_advance.models.salary_advance import HR_GROUP, NOT_DISBURSED_STATES


class BxiDeputation(models.Model):
    _inherit = 'bxi.deputation'

    def action_confirm_arrival(self):
        res = super().action_confirm_arrival()
        self._settle_salary_advances()
        return res

    def _settle_salary_advances(self):
        """The employee leaves the home payroll: the outstanding balance of every advance is
        recovered in the Full and Final Settlement, from the last home payslip."""
        Advance = self.env['bxi.salary.advance'].sudo()
        for deputation in self:
            employee = deputation.employee_id.sudo()
            recovering = Advance.search([('employee_id', '=', employee.id), ('state', '=', 'disbursed')])
            if recovering:
                # When the payroll of the last home month is already confirmed, the balance
                # falls on a later month and is recovered by the host payroll.
                last_day = max(
                    deputation.home_last_date,
                    employee._sa_first_open_payroll_month(deputation.home_last_date))
                for advance in recovering:
                    advance._move_to_fnf(last_day, note=self.env._(
                        "Deputation %(deputation)s to %(country)s: the outstanding balance of %(amount)s is "
                        "recovered in the Full & Final Settlement (payroll of %(month)s).",
                        deputation=deputation.name, country=deputation.host_country_id.name,
                        amount=advance.currency_id.format(advance.amount_balance),
                        month=last_day.strftime('%B %Y')))
            pending = Advance.search([('employee_id', '=', employee.id), ('state', 'in', NOT_DISBURSED_STATES)])
            for advance in pending.filtered(lambda a: a.state != 'draft'):
                advance._notify_group(
                    advance.company_id.sa_hr_user_id, HR_GROUP,
                    self.env._("Salary advance of an employee on deputation: %(name)s", name=advance.name),
                    self.env._("%(employee)s moved to the %(country)s payroll on %(date)s (%(deputation)s). "
                               "Review whether this request can still be paid from the home payroll.",
                               employee=employee.name, country=deputation.host_country_id.name,
                               date=deputation.host_start_date, deputation=deputation.name))
