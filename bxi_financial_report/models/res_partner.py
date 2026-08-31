# -*- coding: utf-8 -*-
from odoo import models, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'

    vendor_category = fields.Selection([
        ('technology', 'Technology'),
        ('miscellaneous', 'Miscellaneous'),
        ('employee', 'Employee'),
        ('travel', 'Travel'),
        ('administration', 'Administration'),
    ], string='Vendor Category', default='miscellaneous')
    is_partner_investor = fields.Boolean(string='Partner Check(Investor)')

