# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class VendorOnboardWizard(models.TransientModel):
    _name = 'vendor.onboard.wizard'
    _description = 'Quick Vendor Onboarding Wizard'

    # Step 1 — Basic Info
    name = fields.Char(string='Vendor / Company Name', required=True)
    vendor_type = fields.Selection([
        ('goods', 'Goods Supplier'),
        ('service', 'Service Provider'),
        ('works', 'Works Contractor'),
        ('both', 'Goods & Services'),
    ], string='Vendor Type', default='goods', required=True)
    company_type = fields.Selection([
        ('company', 'Company'),
        ('individual', 'Individual / Proprietorship'),
        ('partnership', 'Partnership'),
        ('llp', 'LLP'),
        ('public', 'Public Limited'),
    ], string='Company Type', default='company', required=True)
    category_id = fields.Many2one('bxi.vendor.category', string='Category')

    # Step 2 — Contact
    email = fields.Char(string='Email', required=True)
    phone = fields.Char(string='Phone')
    city = fields.Char(string='City')
    state_id = fields.Many2one('res.country.state', string='State')
    country_id = fields.Many2one('res.country', string='Country', default=lambda self: self.env.ref('base.in', raise_if_not_found=False))

    # Step 3 — Compliance
    gstin = fields.Char(string='GSTIN', size=15)
    pan = fields.Char(string='PAN Number', size=10)
    msme_registered = fields.Boolean(string='MSME Registered?')
    msme_number = fields.Char(string='MSME No.')

    # Step 4 — Bank
    bank_name = fields.Char(string='Bank Name')
    bank_account_number = fields.Char(string='Account Number')
    bank_ifsc = fields.Char(string='IFSC Code')

    def action_create_vendor(self):
        self.ensure_one()
        vendor = self.env['bxi.vendor'].create({
            'name': self.name,
            'vendor_type': self.vendor_type,
            'company_type': self.company_type,
            'category_id': self.category_id.id,
            'email': self.email,
            'phone': self.phone,
            'city': self.city,
            'state_id': self.state_id.id,
            'country_id': self.country_id.id,
            'gstin': self.gstin,
            'pan': self.pan,
            'msme_registered': self.msme_registered,
            'msme_number': self.msme_number,
            'bank_name': self.bank_name,
            'bank_account_number': self.bank_account_number,
            'bank_ifsc': self.bank_ifsc,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vendor Created'),
            'res_model': 'bxi.vendor',
            'res_id': vendor.id,
            'view_mode': 'form',
            'target': 'current',
        }
