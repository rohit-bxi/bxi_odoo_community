# -*- coding: utf-8 -*-

from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    customer_type = fields.Selection(
        selection=[
            ('prospect', 'Prospect'),
            ('customer', 'Customer'),
        ],
        string='Customer Type',
        default='prospect',
        tracking=True,
    )
