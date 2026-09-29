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
    question_ids = fields.One2many(
        "performance.review.template.question", "template_id", string="Questions"
    )
    appraisee_question_ids = fields.One2many(
        "performance.review.template.question", "template_id",
        string="Appraisee Questions", domain=[("question_type", "=", "appraisee")],
    )
    manager_question_ids = fields.One2many(
        "performance.review.template.question", "template_id",
        string="Manager Questions", domain=[("question_type", "=", "manager")],
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


class PerformanceReviewTemplateQuestion(models.Model):
    _name = "performance.review.template.question"
    _description = "Performance Review Template Question"
    _order = "question_type, sequence, id"

    template_id = fields.Many2one(
        "performance.review.template", required=True, ondelete="cascade"
    )
    sequence = fields.Integer(default=10)
    question_type = fields.Selection(
        [
            ("appraisee", "Appraisee Question"),
            ("manager", "Manager Question"),
        ],
        required=True,
        default="appraisee",
    )
    question = fields.Text(required=True)
    response_type = fields.Selection(
        [
            ("answer", "Answer Only"),
            ("rating", "Rating Only"),
            ("both", "Answer + Rating"),
        ],
        string="Response Type",
        required=True,
        default="answer",
    )
    rating_scale = fields.Selection(
        [(str(i), f"{i} Star{'s' if i != 1 else ''}") for i in range(1, 6)],
        string="Rating Scale",
        default="5",
    )
    active = fields.Boolean(default=True)

    @api.constrains("response_type", "rating_scale")
    def _check_rating_configuration(self):
        for rec in self:
            if rec.response_type in ("rating", "both") and not rec.rating_scale:
                raise ValidationError(_("Rating Scale is required when the question uses rating."))

    @api.model_create_multi
    def create(self, vals_list):
        """Respect the question tab used in the template.

        The two One2many fields use default_question_type in their context.
        Explicitly apply that context here so a question added from the
        Manager Questions tab can never silently fall back to Appraisee.
        """
        default_type = self.env.context.get("default_question_type")
        if default_type in ("appraisee", "manager"):
            for vals in vals_list:
                if not vals.get("question_type"):
                    vals["question_type"] = default_type
        return super().create(vals_list)
