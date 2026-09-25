# -*- coding: utf-8 -*-
from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    bid_cpo_signoff = fields.Boolean(
        string='CPO Sign-off Required for Bids',
        help="RFP/tender bid declarations must be approved by the CPO before the bid goes out.",
    )
