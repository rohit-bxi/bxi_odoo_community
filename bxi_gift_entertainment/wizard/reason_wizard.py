from odoo import _, fields, models
from odoo.exceptions import UserError


class BxiGiftReasonWizard(models.TransientModel):
    _name = 'bxi.gift.reason.wizard'
    _description = 'Gift Policy Rejection Reason'

    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    action = fields.Selection([('reject', 'Reject')], default='reject', required=True)
    reason = fields.Text(required=True)

    def action_confirm(self):
        self.ensure_one()
        record = self.env[self.res_model].browse(self.res_id)
        line = record.current_approval_line_id
        if not line or (self.env.user not in line.user_ids and not record._gift_is_officer()):
            raise UserError(_("You are not an approver of the current step of %s.", record.name))
        record.sudo()._gift_reject(self.reason)
        return {'type': 'ir.actions.act_window_close'}
