# -*- coding: utf-8 -*-

from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    is_different_shipping_address = fields.Boolean(
        string="Different Shipping Address",
        default=False
    )
    shipping_partner_id = fields.Many2one(
        'res.partner',
        string="Ship To",
        domain="[('customer_type', 'in', ('customer', 'vendor', 'customer_and_vendor'))]"
    )
    shipping_street = fields.Char(string="Street 1")
    shipping_street2 = fields.Char(string="Street 2")
    shipping_city = fields.Char(string="City")
    shipping_state_id = fields.Many2one(
        'res.country.state',
        string="State",
        domain="[('country_id', '=?', shipping_country_id)]"
    )
    shipping_zip = fields.Char(string="Zip")
    shipping_country_id = fields.Many2one(
        'res.country',
        string="Country"
    )

    @api.onchange('shipping_partner_id')
    def _onchange_shipping_partner_id(self):
        if self.shipping_partner_id:
            self.shipping_street = self.shipping_partner_id.street
            self.shipping_street2 = self.shipping_partner_id.street2
            self.shipping_city = self.shipping_partner_id.city
            self.shipping_state_id = self.shipping_partner_id.state_id
            self.shipping_zip = self.shipping_partner_id.zip
            self.shipping_country_id = self.shipping_partner_id.country_id

    @api.onchange('shipping_state_id')
    def _onchange_shipping_state_id(self):
        if self.shipping_state_id:
            self.shipping_country_id = self.shipping_state_id.country_id

    @api.onchange('shipping_country_id')
    def _onchange_shipping_country_id(self):
        if self.shipping_state_id and self.shipping_state_id.country_id != self.shipping_country_id:
            self.shipping_state_id = False

    def _prepare_invoice(self):
        invoice_vals = super()._prepare_invoice()
        if self.is_different_shipping_address:
            invoice_vals.update({
                'is_different_shipping_address': True,
                'shipping_partner_id': self.shipping_partner_id.id if self.shipping_partner_id else False,
                'shipping_street': self.shipping_street,
                'shipping_street2': self.shipping_street2,
                'shipping_city': self.shipping_city,
                'shipping_state_id': self.shipping_state_id.id if self.shipping_state_id else False,
                'shipping_zip': self.shipping_zip,
                'shipping_country_id': self.shipping_country_id.id if self.shipping_country_id else False,
            })
        return invoice_vals

