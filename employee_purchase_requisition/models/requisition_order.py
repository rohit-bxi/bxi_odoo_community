# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class RequisitionOrder(models.Model):
    """Model to add Requisition order details"""
    _name = 'requisition.order'
    _description = 'Requisition order'

    requisition_product_id = fields.Many2one(
        comodel_name='employee.purchase.requisition',
        help='Requisition product.')
    state = fields.Selection(string='State',
                             related='requisition_product_id.state')
    requisition_type = fields.Selection(string='Requisition Type', selection=[
        ('purchase_order', 'Purchase Order'),
        ('internal_transfer', 'Internal Transfer'), ],
                                        help='Type of requisition',
                                        required=True, default='purchase_order')
    product_id = fields.Many2one(comodel_name='product.product', required=True,
                                 help='Product')
    description = fields.Text(string="Description", compute='_compute_name',
                              store=True, readonly=False, precompute=True,
                              help='Product description')
    quantity = fields.Integer(string='Quantity', help='Product quantity')
    uom = fields.Char(related='product_id.uom_id.name',
                      string='Unit of Measure', help='Product unit of measure')
    partner_id = fields.Many2one(comodel_name='res.partner', string='Vendor',
                                 domain="[('customer_type', 'in', ('vendor', 'customer_and_vendor'))]",
                                 help='Vendor for the requisition',
                                 readonly=False)
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related='requisition_product_id.company_id',
        store=True,
        readonly=True,
    )

    @api.constrains('partner_id')
    def _check_partner_customer_type(self):
        for rec in self:
            if rec.partner_id and 'customer_type' in rec.partner_id._fields:
                if rec.partner_id.customer_type not in ('vendor', 'customer_and_vendor'):
                    raise ValidationError("Selected vendor must have type 'Vendor' or 'Customer and Vendor'.")

    @api.depends('product_id')
    def _compute_name(self):
        """Compute product description"""
        for option in self:
            if not option.product_id:
                continue
            product_lang = option.product_id.with_context(
                lang=self.requisition_product_id.employee_id.lang)
            option.description = product_lang.get_product_multiline_description_sale()

    @api.onchange('requisition_type', 'product_id')
    def _onchange_product(self):
        """Fetching product vendors"""
        partner_model = self.env['res.partner']
        if 'customer_type' in partner_model._fields:
            domain = [('customer_type', 'in', ('vendor', 'customer_and_vendor'))]
        else:
            domain = [('supplier_rank', '>', 0)]
        return {'domain': {'partner_id': domain}}
