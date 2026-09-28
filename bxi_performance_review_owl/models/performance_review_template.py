from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PerformanceReviewTemplate(models.Model):
    _name = "performance.review.template"
    _description = "Performance Review Template"
    _order = "name"

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    active = fields.Boolean(default=True)
    line_ids = fields.One2many(
        "performance.review.template.line", "template_id", string="Performance Parameters"
    )

    @api.constrains("line_ids")
    def _check_weightage(self):
        for rec in self:
            total = sum(rec.line_ids.mapped("weightage"))
            if total > 100.0001:
                raise ValidationError(_("Template weightage cannot exceed 100%%."))


class PerformanceReviewTemplateLine(models.Model):
    _name = "performance.review.template.line"
    _description = "Performance Review Template Line"
    _order = "sequence, id"

    template_id = fields.Many2one(
        "performance.review.template", required=True, ondelete="cascade"
    )
    sequence = fields.Integer(default=10)
    category = fields.Char(required=True)
    weightage = fields.Float(required=True, digits=(16, 2))
    target = fields.Char()
    description = fields.Char()
    active = fields.Boolean(default=True)

    @api.constrains("weightage")
    def _check_weightage(self):
        for rec in self:
            if rec.weightage < 0 or rec.weightage > 100:
                raise ValidationError(_("Weightage must be between 0 and 100."))
