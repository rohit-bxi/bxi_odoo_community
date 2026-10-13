# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    missed_checkout_lwp = fields.Boolean(
        related='company_id.missed_checkout_lwp', readonly=False)
    missed_checkout_lwp_start_date = fields.Date(
        related='company_id.missed_checkout_lwp_start_date', readonly=False)
    attendance_regularization_start_date = fields.Date(
        related='company_id.attendance_regularization_start_date', readonly=False)
