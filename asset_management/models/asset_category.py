# -*- coding: utf-8 -*-
from odoo import models, fields, api


class AssetCategory(models.Model):
    _name = 'asset.category'
    _description = 'Asset Category'
    _order = 'sequence asc, id asc'

    name = fields.Char(string='Category Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10, help="Order of the category.")
    color = fields.Integer(string='Color Index')
    description = fields.Text(string='Description')
    active = fields.Boolean(string='Active', default=True)

    asset_type_ids = fields.One2many(
        'asset.type',
        'category_id',
        string='Asset Types'
    )
    asset_type_count = fields.Integer(
        string='Asset Types Count',
        compute='_compute_asset_type_count'
    )

    @api.depends('asset_type_ids')
    def _compute_asset_type_count(self):
        for rec in self:
            rec.asset_type_count = len(rec.asset_type_ids)

    def action_view_asset_types(self):
        self.ensure_one()
        return {
            'name': 'Asset Types',
            'type': 'ir.actions.act_window',
            'res_model': 'asset.type',
            'view_mode': 'list,form',
            'domain': [('category_id', '=', self.id)],
            'context': {
                'default_category_id': self.id,
                'search_default_group_by_category': 1,
            },
        }

