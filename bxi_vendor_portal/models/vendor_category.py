# -*- coding: utf-8 -*-
from odoo import models, fields


class VendorCategory(models.Model):
    _name = 'bxi.vendor.category'
    _description = 'Vendor Category'
    _parent_name = 'parent_id'
    _parent_store = True
    _rec_name = 'complete_name'
    _order = 'complete_name'

    name = fields.Char(string='Category Name', required=True)
    code = fields.Char(string='Category Code')
    complete_name = fields.Char(
        string='Complete Name',
        compute='_compute_complete_name',
        store=True,
    )
    parent_id = fields.Many2one(
        'bxi.vendor.category',
        string='Parent Category',
        ondelete='restrict',
        index=True,
    )
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many('bxi.vendor.category', 'parent_id', string='Sub-Categories')
    description = fields.Text(string='Description')
    active = fields.Boolean(string='Active', default=True)
    vendor_count = fields.Integer(
        string='Vendors',
        compute='_compute_vendor_count',
    )

    def _compute_complete_name(self):
        for cat in self:
            if cat.parent_id:
                cat.complete_name = f'{cat.parent_id.complete_name} / {cat.name}'
            else:
                cat.complete_name = cat.name

    def _compute_vendor_count(self):
        for cat in self:
            cat.vendor_count = self.env['bxi.vendor'].search_count([('category_id', '=', cat.id)])
