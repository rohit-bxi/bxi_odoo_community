from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class PerformanceBonusCycle(models.Model):
    _name = "performance.bonus.cycle"
    _description = "Performance Bonus Cycle"
    _order = "date_start desc"

    name = fields.Char(required=True)
    plan_id = fields.Many2one("performance.bonus.plan", required=True, ondelete="restrict")
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    bonus_pay_date = fields.Date(compute="_compute_bonus_pay_date", store=True)

    state = fields.Selection([
        ("draft", "Draft"),
        ("review", "Rating Review"),
        ("approved", "Approved"),
        ("paid", "Paid"),
        ("cancelled", "Cancelled"),
    ], default="draft", required=True)

    line_ids = fields.One2many("performance.bonus.line", "cycle_id")

    @api.depends("date_end")
    def _compute_bonus_pay_date(self):
        for rec in self:
            rec.bonus_pay_date = rec.date_end + timedelta(days=60) if rec.date_end else False

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        for rec in self:
            if rec.date_end < rec.date_start:
                raise ValidationError("Bonus cycle end date cannot be before start date.")

    def action_generate_employees(self):
        self.ensure_one()
        if self.state not in ("draft", "review"):
            raise UserError("Employees can only be generated in Draft or Rating Review.")

        self.line_ids.unlink()
        employees = self.env["hr.employee"].sudo().search([
            ("active", "=", True),
            ("company_id", "=", self.company_id.id),
        ])

        Line = self.env["performance.bonus.line"].sudo()
        for employee in employees:
            line = Line.create(Line._prepare_line_vals(employee, self))
            line._refresh_review_links()
            line._set_final_calibration_from_reviews()
            line._compute_policy_values()
            line._compute_lwp_days()
            line._compute_lwp_factor()
            line._compute_bonus_amount()

        self.state = "review"
        return True

    def action_refresh_ratings(self):
        self.ensure_one()
        for line in self.line_ids:
            line._refresh_review_links()
            line._set_final_calibration_from_reviews()
            line._compute_policy_values()
            line._compute_lwp_days()
            line._compute_bonus_amount()
        return True

    def action_approve(self):
        self.ensure_one()
        errors = []
        for line in self.line_ids.filtered("eligible"):
            if not line.final_calibration:
                errors.append(line.employee_id.name)
        if errors:
            raise UserError(
                "Eligible employees without a final calibration rating: %s"
                % ", ".join(errors)
            )
        self.state = "approved"

    def action_mark_paid(self):
        self.ensure_one()
        if self.state != "approved":
            raise UserError("Only an approved bonus cycle can be marked Paid.")
        self.state = "paid"

    def action_cancel(self):
        self.state = "cancelled"

    def action_reset_draft(self):
        self.state = "draft"
