from odoo import fields, models


class BxiEbWorkPattern(models.Model):
    _name = 'bxi.eb.work.pattern'
    _description = 'Equitable Benefit Work Pattern'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    days_per_week = fields.Float(string='Office Days / Week')
    is_shift = fields.Boolean(string='Shift Based', help="Odd hour / day / week or night shift work.")
    description = fields.Text()
    active = fields.Boolean(default=True)
    rate_ids = fields.One2many('bxi.eb.rate', 'work_pattern_id', string='Rates')

    _code_unique = models.Constraint('unique(code)', 'The work pattern code must be unique.')
