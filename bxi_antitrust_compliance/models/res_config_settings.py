# -*- coding: utf-8 -*-
from odoo import models, fields

from .antitrust_mixin import CONTACT_EMAIL_PARAM, DEFAULT_CONTACT_EMAIL


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    antitrust_contact_email = fields.Char(
        string='Compliance Contact Email',
        config_parameter=CONTACT_EMAIL_PARAM,
        default=DEFAULT_CONTACT_EMAIL,
    )
    bid_cpo_signoff = fields.Boolean(related='company_id.bid_cpo_signoff', readonly=False)
