# -*- coding: utf-8 -*-
from odoo import fields, models


class HdfcReverseWizard(models.TransientModel):
    _name = 'hdfc.reverse.wizard'
    _description = 'Reverse HDFC Payout'

    batch_id = fields.Many2one('hdfc.payout.batch', required=True, readonly=True, ondelete='cascade')
    reason = fields.Text(required=True)

    def action_reverse(self):
        self.ensure_one()
        return self.batch_id._reverse(self.reason)
