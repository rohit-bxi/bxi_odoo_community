from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PerformanceBonusPlan(models.Model):
    _name = "performance.bonus.plan"
    _description = "Performance Bonus Plan"
    _order = "sequence, name"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    bonus_type = fields.Selection([
        ("yepb", "YEPB / PB - India"),
        ("ogpb", "OGPB - Europe / APAC / ROW"),
        ("ogsm", "OGSM Linked - Americas / Canada"),
    ], required=True, default="yepb")

    applicable_grades = fields.Char(
        default="E0,E1,E2,E3",
        help="Comma-separated eligible grades."
    )
    target_bonus_percentage = fields.Float(
        string="Target Bonus %",
        help="Enter the approved target bonus percentage from the employee's compensation plan."
    )
    company_performance_factor = fields.Float(
        string="Company Performance Factor",
        default=1.0,
        help="Company performance/affordability factor. 1.0 means 100%."
    )
    include_lwp_adjustment = fields.Boolean(
        default=True,
        help="Apply proportional reduction for approved LWP days."
    )
    rating_aggregation = fields.Selection([
        ("manual", "HR Sets Final Rating"),
        ("average", "Average of Available Quarterly Ratings"),
        ("latest", "Latest Available Quarterly Rating"),
    ], default="manual", required=True,
       help="The policy document does not specify how quarterly calibrations are converted to an annual rating. Keep Manual unless HR approves another rule.")

    rating_rule_ids = fields.One2many(
        "performance.bonus.rating.rule",
        "plan_id",
        string="Rating Payout Rules"
    )
    notes = fields.Text()

    @api.constrains("target_bonus_percentage", "company_performance_factor")
    def _check_values(self):
        for rec in self:
            if rec.target_bonus_percentage < 0:
                raise ValidationError("Target Bonus % cannot be negative.")
            if rec.company_performance_factor < 0:
                raise ValidationError("Company Performance Factor cannot be negative.")


class PerformanceBonusRatingRule(models.Model):
    _name = "performance.bonus.rating.rule"
    _description = "Performance Bonus Rating Rule"
    _order = "sequence, min_rating"

    plan_id = fields.Many2one("performance.bonus.plan", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    min_rating = fields.Float(required=True)
    max_rating = fields.Float(required=True)
    payout_factor = fields.Float(
        required=True,
        default=1.0,
        help="1.0 = 100% of target bonus; 0.5 = 50%; 1.2 = 120%."
    )

    @api.constrains("min_rating", "max_rating", "payout_factor")
    def _check_rule(self):
        for rec in self:
            if rec.max_rating < rec.min_rating:
                raise ValidationError("Maximum rating must be greater than or equal to minimum rating.")
            if rec.payout_factor < 0:
                raise ValidationError("Payout factor cannot be negative.")
