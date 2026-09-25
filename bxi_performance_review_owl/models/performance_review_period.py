from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PerformanceReviewPeriod(models.Model):
    _name = "performance.review.period"
    _description = "Performance Review Period"
    _order = "date_start desc"

    name = fields.Char(required=True)
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        for rec in self:
            if rec.date_end < rec.date_start:
                raise ValidationError(_("End date cannot be before start date."))

    _sql_constraints = [
        (
            "period_name_company_unique",
            "unique(name, company_id)",
            "A review period with this name already exists for this company.",
        )
    ]
