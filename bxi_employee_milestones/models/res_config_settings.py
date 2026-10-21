# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    milestone_hr_email = fields.Char(
        related='company_id.milestone_hr_email', readonly=False)
