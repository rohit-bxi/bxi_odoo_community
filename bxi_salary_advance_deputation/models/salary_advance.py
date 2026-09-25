from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.bxi_salary_advance.models.salary_advance import HR_GROUP


class BxiSalaryAdvance(models.Model):
    _inherit = 'bxi.salary.advance'

    recover_at_host = fields.Boolean(
        string='Recover at Host Location', compute='_compute_recover_at_host', store=True,
        help="The employee is on a host country payroll and part of the balance falls after the last "
             "home payslip: the host payroll recovers it.")

    @api.depends('state', 'installment_ids.state', 'installment_ids.due_date', 'employee_id.is_on_deputation')
    def _compute_recover_at_host(self):
        Deputation = self.env['bxi.deputation'].sudo()
        for rec in self:
            deputation = Deputation.search([
                ('employee_id', '=', rec.employee_id.id), ('state', '=', 'transferred'),
            ], limit=1) if rec.state == 'fnf' and rec.employee_id.is_on_deputation else Deputation
            last_home_month = deputation.home_last_date.replace(day=1) if deputation.home_last_date else None
            rec.recover_at_host = bool(last_home_month) and any(
                inst.state == 'pending' and inst.due_date > last_home_month for inst in rec.installment_ids)

    def action_open_host_recovery_wizard(self):
        self.ensure_one()
        if not self.recover_at_host or not self.env.user.has_group(HR_GROUP):
            raise UserError(self.env._("Only HR can record the recovery of a balance due at the host location."))
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Record Host Recovery'),
            'res_model': 'bxi.salary.advance.host.recovery.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_advance_id': self.id},
        }
