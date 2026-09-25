from odoo import api, fields, models, _, SUPERUSER_ID
from odoo.exceptions import AccessError, UserError, ValidationError


class PerformanceReview(models.Model):
    _name = "performance.review"
    _description = "Performance Review"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(required=True, copy=False, default="New", tracking=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    period_id = fields.Many2one("performance.review.period", required=True, tracking=True)
    template_id = fields.Many2one("performance.review.template", required=True, tracking=True)
    employee_id = fields.Many2one("hr.employee", required=True, tracking=True)
    employee_user_id = fields.Many2one(related="employee_id.user_id", store=True, index=True)
    employee_email = fields.Char(related="employee_id.work_email", store=True)
    department_id = fields.Many2one(related="employee_id.department_id", store=True)
    manager_id = fields.Many2one("hr.employee", tracking=True)
    manager_user_id = fields.Many2one(related="manager_id.user_id", store=True, index=True)
    manager_email = fields.Char(related="manager_id.work_email", store=True)
    second_manager_id = fields.Many2one("hr.employee", tracking=True)
    second_manager_user_id = fields.Many2one(related="second_manager_id.user_id", store=True, index=True)
    second_manager_email = fields.Char(related="second_manager_id.work_email", store=True)
    company_logo = fields.Binary(related="company_id.logo", string="Company Logo", readonly=True)

    year = fields.Integer(compute="_compute_period_info", store=True)
    quarter = fields.Selection(
        [("q1", "Q1"), ("q2", "Q2"), ("q3", "Q3"), ("q4", "Q4")],
        compute="_compute_period_info", store=True
    )

    line_ids = fields.One2many("performance.review.line", "review_id", copy=True)
    successor_1 = fields.Char()
    successor_2 = fields.Char()
    appraisee_remarks = fields.Text()
    manager_remarks = fields.Text()
    calibration = fields.Selection(
        [
            ('5', 'Outstanding'),
            ('4', 'Exceeds Expectations'),
            ('3', 'Meets Expectations'),
            ('2', 'Needs Improvement'),
            ('1', 'Unsatisfactory'),
        ],
        string='Calibration',
    )    
    reviewer_remarks = fields.Text()

    final_score = fields.Float(compute="_compute_final_score", store=True, digits=(16, 2))

    state = fields.Selection(
        [
            ("draft", "Employee Review"),
            ("manager_review", "Manager Review"),
            ("second_manager_review", "Second Level Review"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )

    employee_submitted_date = fields.Datetime(readonly=True)
    manager_submitted_date = fields.Datetime(readonly=True)
    second_manager_submitted_date = fields.Datetime(readonly=True)
    completed_date = fields.Datetime(readonly=True)

    can_edit_self = fields.Boolean(compute="_compute_permissions")
    can_edit_manager = fields.Boolean(compute="_compute_permissions")
    can_edit_second = fields.Boolean(compute="_compute_permissions")
    can_edit_hr = fields.Boolean(compute="_compute_permissions")

    @api.depends("period_id.date_start")
    def _compute_period_info(self):
        for rec in self:
            date = rec.period_id.date_start
            if not date:
                rec.year = False
                rec.quarter = False
                continue
            rec.year = date.year
            rec.quarter = "q%d" % (((date.month - 1) // 3) + 1)

    @api.depends("line_ids.manager_score", "line_ids.weightage")
    def _compute_final_score(self):
        for rec in self:
            rec.final_score = sum(
                float(line.manager_score or 0.0) * float(line.weightage or 0.0) / 100.0
                for line in rec.line_ids
                if line.manager_score
            )

    def _is_hr(self):
        return self.env.user.has_group("bxi_performance_review_owl.group_performance_review_hr")

    @api.depends("employee_user_id", "manager_user_id", "second_manager_user_id", "state")
    def _compute_permissions(self):
        is_hr = self._is_hr()
        user = self.env.user
        for rec in self:
            rec.can_edit_hr = is_hr
            rec.can_edit_self = is_hr or (
                rec.state == "draft" and rec.employee_user_id == user
            )
            rec.can_edit_manager = is_hr or (
                rec.state == "manager_review" and rec.manager_user_id == user
            )
            rec.can_edit_second = is_hr or (
                rec.state == "second_manager_review" and rec.second_manager_user_id == user
            )

    @api.model
    def get_current_user_id(self):
        return self.env.user.id

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if "employee_id" in fields_list and not vals.get("employee_id"):
            employee = self.env["hr.employee"].search(
                [("user_id", "=", self.env.user.id), ("active", "=", True)], limit=1
            )
            if employee:
                vals["employee_id"] = employee.id
        if "period_id" in fields_list and not vals.get("period_id"):
            period = self.env["performance.review.period"].search(
                [
                    ("date_start", "<=", fields.Date.today()),
                    ("date_end", ">=", fields.Date.today()),
                    ("active", "=", True),
                    ("company_id", "=", self.env.company.id),
                ],
                order="date_start desc", limit=1,
            )
            if period:
                vals["period_id"] = period.id
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        if not self._is_hr():
            raise AccessError(_("Only HR can create Performance Reviews. Please ask HR to generate the review."))
        for vals in vals_list:
            employee_id = vals.get("employee_id")
            if not employee_id:
                raise UserError(_("An Employee is required to create a Performance Review."))
            employee = self.env["hr.employee"].browse(employee_id).exists()
            if not employee:
                raise UserError(_("The selected Employee does not exist."))
            if not vals.get("period_id"):
                raise UserError(_("A Review Period is required to create a Performance Review."))
            if not vals.get("template_id"):
                raise UserError(_("A Performance Review Template is required to create a Performance Review."))
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("performance.review") or "New"
            vals.setdefault("company_id", employee.company_id.id or self.env.company.id)
            vals.setdefault("manager_id", employee.parent_id.id if employee.parent_id else False)
            vals.setdefault(
                "second_manager_id",
                employee.parent_id.parent_id.id
                if employee.parent_id and employee.parent_id.parent_id else False,
            )
        records = super().create(vals_list)
        records._create_lines_from_template()
        return records

    def _create_lines_from_template(self):
        for review in self:
            if review.line_ids:
                continue
            commands = []
            for line in review.template_id.line_ids.filtered("active"):
                commands.append((0, 0, {
                    "sequence": line.sequence,
                    "category": line.category,
                    "weightage": line.weightage,
                    "target": line.target,
                    "description": line.description,
                }))
            if commands:
                self.env["performance.review.line"].with_user(SUPERUSER_ID).create([
                    dict(command[2], review_id=review.id) for command in commands
                ])

    def _check_employee(self):
        for rec in self:
            if not (self._is_hr() or rec.employee_user_id == self.env.user):
                raise AccessError(_("Only the assigned employee or HR can perform this action."))

    def _check_manager(self):
        for rec in self:
            if not (self._is_hr() or rec.manager_user_id == self.env.user):
                raise AccessError(_("Only the reporting manager or HR can perform this action."))

    def _check_second_manager(self):
        for rec in self:
            if not (self._is_hr() or rec.second_manager_user_id == self.env.user):
                raise AccessError(_("Only the second-level manager or HR can perform this action."))

    def action_submit_employee(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("This review is not in Employee Review stage."))
            rec._check_employee()
            if not rec.manager_id:
                raise UserError(_("No reporting manager is configured for this employee."))
            if not rec.employee_id.user_id and not self._is_hr():
                raise UserError(_("The employee must have an Odoo user linked to the employee profile."))
            rec.write({
                "state": "manager_review",
                "employee_submitted_date": fields.Datetime.now(),
            })

    def action_submit_manager(self):
        for rec in self:
            if rec.state != "manager_review":
                raise UserError(_("This review is not in Manager Review stage."))
            rec._check_manager()
            if rec.second_manager_id:
                rec.write({
                    "state": "second_manager_review",
                    "manager_submitted_date": fields.Datetime.now(),
                })
            else:
                rec.write({
                    "state": "completed",
                    "manager_submitted_date": fields.Datetime.now(),
                    "completed_date": fields.Datetime.now(),
                })

    def action_submit_second_manager(self):
        for rec in self:
            if rec.state != "second_manager_review":
                raise UserError(_("This review is not in Second Level Review stage."))
            rec._check_second_manager()
            rec.write({
                "state": "completed",
                "second_manager_submitted_date": fields.Datetime.now(),
                "completed_date": fields.Datetime.now(),
            })

    def action_cancel(self):
        if not self._is_hr():
            raise AccessError(_("Only HR can cancel a Performance Review."))
        self.write({"state": "cancelled"})

    def action_reset_to_draft(self):
        if not self._is_hr():
            raise AccessError(_("Only HR can reset a Performance Review."))
        self.write({
            "state": "draft",
            "employee_submitted_date": False,
            "manager_submitted_date": False,
            "second_manager_submitted_date": False,
            "completed_date": False,
        })

    def action_print_report(self):
        return self.env.ref("bxi_performance_review_owl.action_report_performance_review").report_action(self)

    def write(self, vals):
        is_hr = self._is_hr()
        if is_hr:
            return super().write(vals)
        protected_self = {"successor_1", "successor_2", "appraisee_remarks"}
        manager_fields = {"manager_remarks"}
        second_fields = {"calibration", "reviewer_remarks"}
        for rec in self:
            if any(k in vals for k in protected_self) and not rec.can_edit_self:
                raise AccessError(_("You cannot modify employee self-review fields at this stage."))
            if any(k in vals for k in manager_fields) and not rec.can_edit_manager:
                raise AccessError(_("You cannot modify manager review fields at this stage."))
            if any(k in vals for k in second_fields) and not rec.can_edit_second:
                raise AccessError(_("You cannot modify second-level review fields at this stage."))
        return super().write(vals)


class PerformanceReviewLine(models.Model):
    _name = "performance.review.line"
    _description = "Performance Review Line"
    _order = "sequence, id"

    review_id = fields.Many2one("performance.review", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    category = fields.Char(required=True)
    weightage = fields.Float(required=True, digits=(16, 2))
    target = fields.Char()
    description = fields.Char()
    self_achievement = fields.Text(string="Appraisee Actual Achievement (Self)")
    manager_review = fields.Text(string="Appraise Review (RM)")
    manager_score = fields.Selection(
        selection=[
            ("1", "1"),
            ("2", "2"),
            ("3", "3"),
            ("4", "4"),
            ("5", "5"),
        ],
        string="Appraise Score (RM)",
    )
    @api.constrains("manager_score", "category")
    def _check_manager_score(self):
        for record in self:
            if not record.manager_score:
                continue

            score = float(record.manager_score)
            category = (record.category or "").lower().strip()

            # Revenue / Revenue Enablement → only 1 or 2
            if "revenue" in category:
                if score not in (1.0, 2.0):
                    raise ValidationError(
                        _(
                            "Revenue / Revenue Enablement score must be either 1 or 2."
                        )
                    )

            # All other categories → 1 to 5
            elif score < 1 or score > 5:
                raise ValidationError(
                    _("Manager Score must be between 1 and 5.")
                )
                
    # @api.constrains("manager_score")
    # def _check_manager_score(self):
    #     for rec in self:
    #         if rec.manager_score < 0 or rec.manager_score > 100:
    #             raise ValidationError(_("Manager score must be between 0 and 100."))

    def write(self, vals):
        is_hr = self.env.user.has_group("bxi_performance_review_owl.group_performance_review_hr")
        if is_hr:
            return super().write(vals)
        for rec in self:
            review = rec.review_id
            if review.state == "draft":
                allowed = review.employee_user_id == self.env.user
                allowed_fields = {"self_achievement"}
            elif review.state == "manager_review":
                allowed = review.manager_user_id == self.env.user
                allowed_fields = {"manager_review", "manager_score"}
            elif review.state == "second_manager_review":
                allowed = review.second_manager_user_id == self.env.user
                allowed_fields = {"manager_review", "manager_score"}
            else:
                allowed = False
                allowed_fields = set()
            if not allowed or any(k not in allowed_fields for k in vals):
                raise AccessError(_("You cannot modify this Performance Review line at this stage."))
        return super().write(vals)
