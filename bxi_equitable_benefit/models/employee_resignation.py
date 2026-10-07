from odoo import models


class EmployeeResignation(models.Model):
    _inherit = 'employee.resignation'

    def write(self, vals):
        res = super().write(vals)
        if vals.get('state') == 'approved':
            self._create_equitable_benefit_fnf()
        elif {'approved_last_working_day', 'last_working_day'} & set(vals):
            self.filtered(lambda r: r.state == 'approved')._create_equitable_benefit_fnf()
        return res

    def _create_equitable_benefit_fnf(self):
        """Separating employees get a pro-rata payout in their Full & Final Settlement."""
        for resignation in self:
            last_day = resignation.approved_last_working_day or resignation.last_working_day
            if last_day and resignation.employee_id:
                resignation.employee_id._eb_settle_separation(last_day, resignation)
