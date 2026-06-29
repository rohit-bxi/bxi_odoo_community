from odoo import models, fields
from odoo.exceptions import ValidationError

import base64
import logging
import json
import random

from datetime import datetime


_logger = logging.getLogger(__name__)


class ICICIOtpWizard(models.TransientModel):
    _name = 'icici.otp.wizard'
    _description = 'ICICI OTP Wizard'

    otp = fields.Char(
        string='OTP',
        required=True
    )

    payslip_ids = fields.Many2many(
        'hr.payslip',
        string='Payslips',
        required=True
    )
    payment_date = fields.Date(
        string='Payment Date',
        required=True,
        default=fields.Date.today
    )

    def action_confirm_otp(self):

        self.ensure_one()

        try:
            self.payslip_ids.process_bulk_payment(
                self.otp,
                self.payment_date
            )

            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }

        except Exception as e:
            _logger.exception(
                "ICICI BULK PAYMENT ERROR"
            )
            raise ValidationError(str(e))


class IciciReverseWizard(models.TransientModel):
    _name = 'icici.reverse.wizard'

    payslip_id = fields.Many2one('hr.payslip')
    file_seq_num = fields.Char(required=True)    
    def action_reverse(self):
        self.ensure_one()

        if not self.file_seq_num:
                raise ValidationError(
                    "Please enter File Sequence Number."
                )
        
        return self.payslip_id.action_reverse_payment(
            self.file_seq_num
        )