# -*- coding: utf-8 -*-
from odoo import models, fields, api


class VendorAsnLine(models.Model):
    _name = 'bxi.vendor.asn.line'
    _description = 'ASN Line Item'

    asn_id = fields.Many2one('bxi.vendor.asn', string='ASN Reference', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product / Item', required=True)
    description = fields.Char(string='Description', compute='_compute_description', store=True)
    po_line_id = fields.Many2one('purchase.order.line', string='PO Line Reference')
    qty = fields.Float(string='Dispatched Qty', required=True, digits=(12, 3))
    po_qty = fields.Float(string='PO Ordered Qty', compute='_compute_po_qty', store=True)
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure', related='product_id.uom_id', store=True)
    unit_price = fields.Float(string='Unit Price', digits=(12, 2))
    grn_qty = fields.Float(string='GRN Received Qty', digits=(12, 3))
    variance_qty = fields.Float(string='Variance Qty', compute='_compute_variance', store=True)
    batch_lot = fields.Char(string='Batch / Lot Number')
    expiry_date = fields.Date(string='Item Expiry Date')

    @api.depends('product_id')
    def _compute_description(self):
        for line in self:
            line.description = line.product_id.name if line.product_id else ''

    @api.depends('po_line_id')
    def _compute_po_qty(self):
        for line in self:
            line.po_qty = line.po_line_id.product_qty if line.po_line_id else 0.0

    @api.depends('qty', 'grn_qty')
    def _compute_variance(self):
        for line in self:
            line.variance_qty = line.grn_qty - line.qty if line.grn_qty else 0.0
