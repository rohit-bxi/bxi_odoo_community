from odoo import fields, models, _
from odoo.exceptions import UserError


class GeneratePerformanceReviewWizard(models.TransientModel):
    _name = "generate.performance.review.wizard"
    _description = "Generate Performance Reviews"

    period_id = fields.Many2one(
        "performance.review.period",
        required=True,
    )

    template_id = fields.Many2one(
        "performance.review.template",
        required=True,
    )

    employee_ids = fields.Many2many(
        "hr.employee",
        string="Employees",
        domain="[('active', '=', True)]",
    )

    def action_generate(self):
        self.ensure_one()

        if not self.env.user.has_group(
            "bxi_performance_review_owl.group_performance_review_hr"
        ):
            raise UserError(
                _("Only HR can generate Performance Reviews.")
            )

        employees = (
            self.employee_ids
            or self.env["hr.employee"].search(
                [("active", "=", True)]
            )
        )

        if not employees:
            raise UserError(
                _("No active employees were found.")
            )

        Review = self.env["performance.review"]

        existing = Review.search([
            ("period_id", "=", self.period_id.id),
            ("employee_id", "in", employees.ids),
        ])

        existing_ids = set(
            existing.mapped("employee_id").ids
        )

        vals_list = []

        for employee in employees:
            if employee.id in existing_ids:
                continue

            vals_list.append({
                "period_id": self.period_id.id,
                "template_id": self.template_id.id,
                "employee_id": employee.id,
                "company_id": (
                    employee.company_id.id
                    or self.env.company.id
                ),
            })

        if not vals_list:
            raise UserError(
                _(
                    "Performance Reviews already exist "
                    "for all selected employees for this period."
                )
            )

        Review.create(vals_list)

        return {
            "type": "ir.actions.act_window",
            "name": _("Performance Reviews"),
            "res_model": "performance.review",
            "view_mode": "list,form",
            "target": "current",
        }