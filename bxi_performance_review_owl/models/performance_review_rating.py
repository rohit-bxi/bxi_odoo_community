from odoo import fields, models


class PerformanceReviewRating(models.Model):
    _name = "performance.review.rating"
    _description = "Performance Review Rating"
    _order = "sequence, id"

    name = fields.Char(required=True)
    score = fields.Float(required=True)
    description = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
