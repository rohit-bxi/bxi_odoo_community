from odoo import models, fields


class BxiCertificationRefuseWizard(models.TransientModel):
    _name = 'bxi.certification.refuse.wizard'
    _description = 'Refuse Certification Request'

    request_id = fields.Many2one('bxi.certification.request', string='Certification Request', required=True)
    reason = fields.Text(string='Reason', required=True)

    def action_refuse(self):
        self.ensure_one()
        self.request_id._check_can_refuse()
        self.request_id._action_refuse(self.reason)
        return {'type': 'ir.actions.act_window_close'}
