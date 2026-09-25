from odoo import models


class EmployeeResignation(models.Model):
    _inherit = 'employee.resignation'

    def write(self, vals):
        res = super().write(vals)
        if vals.get('state') == 'approved':
            self._create_equitable_benefit_fnf()
        return res

    def _create_equitable_benefit_fnf(self):
        """Separating employees get a pro-rata payout in their Full & Final Settlement."""
        Payout = self.env['bxi.eb.payout'].sudo()
        for resignation in self:
            last_day = resignation.approved_last_working_day or resignation.last_working_day
            if not last_day or not resignation.employee_id:
                continue
            has_assignment = self.env['bxi.eb.assignment'].sudo().search_count([
                ('employee_id', '=', resignation.employee_id.id), ('state', '=', 'approved')], limit=1)
            if has_assignment:
                Payout._create_fnf_payout(resignation.employee_id, last_day, resignation)
