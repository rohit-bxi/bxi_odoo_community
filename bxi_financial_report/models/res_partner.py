# -*- coding: utf-8 -*-
from odoo import models, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'

    functional_name = fields.Char(string='Functional Name')
    vendor_category = fields.Selection([
        ('technology', 'Technology'),
        ('miscellaneous', 'Miscellaneous'),
        ('employee', 'Employee'),
        ('travel', 'Travel'),
        ('administration', 'Administration'),
    ], string='Vendor Category', default='miscellaneous')
    is_partner_investor = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
    ], string='Investor', default='no')
    is_partner = fields.Selection([
        ('no', 'No'),
        ('yes', 'Yes'),
    ], string='Partner', default='no')
