# -*- coding: utf-8 -*-
from odoo import models, fields


class AssetStage(models.Model):
    _name = 'asset.stage'
    _description = 'Asset Stage'
    _order = 'sequence asc, id asc'

    name = fields.Char(string='Stage Name', required=True, translate=True)
    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help="Used to order stages. Lower sequence appears first in form statusbar and Kanban."
    )
    fold = fields.Boolean(
        string='Folded in Kanban',
        default=False,
        help="This stage will be folded by default in the Kanban view."
    )
    active = fields.Boolean(string='Active', default=True)
    description = fields.Text(string='Description')
