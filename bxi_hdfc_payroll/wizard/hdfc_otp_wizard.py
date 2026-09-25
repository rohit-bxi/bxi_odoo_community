# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class HdfcOtpWizard(models.TransientModel):
    _name = 'hdfc.otp.wizard'
    _description = 'HDFC OTP Verification'

    batch_id = fields.Many2one('hdfc.payout.batch', required=True, readonly=True, ondelete='cascade')
    otp = fields.Char(string='OTP')
    message = fields.Char(readonly=True)
    amount_total = fields.Monetary(related='batch_id.amount_total')
    currency_id = fields.Many2one(related='batch_id.currency_id')
    line_count = fields.Integer(related='batch_id.line_count')
    otp_expires_at = fields.Datetime(related='batch_id.otp_expires_at')

    def action_submit(self):
        self.ensure_one()
        otp = (self.otp or '').strip()
        if not otp:
            raise UserError(_('Please enter the OTP.'))
        # never keep the OTP longer than needed
        self.otp = False
        return self.batch_id._submit_with_otp(otp)

    def action_resend(self):
        self.ensure_one()
        self.otp = False
        return self.batch_id.action_request_otp()
