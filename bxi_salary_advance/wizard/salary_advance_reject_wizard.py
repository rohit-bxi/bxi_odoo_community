from odoo import fields, models


class BxiSalaryAdvanceRejectWizard(models.TransientModel):
    _name = 'bxi.salary.advance.reject.wizard'
    _description = 'Reject Salary Advance'

    advance_id = fields.Many2one('bxi.salary.advance', string='Salary Advance', required=True)
    reason = fields.Text(string='Reason', required=True)

    def action_reject(self):
        self.ensure_one()
        self.advance_id._check_can_reject()
        self.advance_id._action_reject(self.reason)
        return {'type': 'ir.actions.act_window_close'}
