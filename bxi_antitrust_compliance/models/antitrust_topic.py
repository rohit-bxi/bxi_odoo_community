# -*- coding: utf-8 -*-
from odoo import models, fields


class AntitrustTopic(models.Model):
    _name = 'antitrust.topic'
    _description = 'Antitrust Prohibited Topic'
    _order = 'category, sequence, id'

    name = fields.Char(string='Topic', required=True, translate=True)
    sequence = fields.Integer(default=10)
    category = fields.Selection(
        [
            ('discussion', 'Do not discuss / agree with competitors'),
            ('general', 'General rule: avoid engagements involving'),
        ],
        string='Category',
        required=True,
        default='discussion',
    )
    active = fields.Boolean(default=True)
