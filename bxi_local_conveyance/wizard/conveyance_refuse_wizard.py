from odoo import fields, models


class BxiConveyanceRefuseWizard(models.TransientModel):
    _name = 'bxi.conveyance.refuse.wizard'
    _description = 'Refuse Conveyance Claim'

    expense_ids = fields.Many2many('hr.expense', string='Claims', required=True)
    reason = fields.Text(string='Reason', required=True)

    def action_refuse(self):
        self.ensure_one()
        self.expense_ids._conveyance_refuse(self.reason)
        return {'type': 'ir.actions.act_window_close'}
