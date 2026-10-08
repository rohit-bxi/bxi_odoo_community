from datetime import date

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PerformanceBonusLine(models.Model):
    _name = "performance.bonus.line"
    _description = "Performance Bonus Employee"
    _order = "eligible desc, employee_id"

    cycle_id = fields.Many2one(
        "performance.bonus.cycle", required=True, ondelete="cascade"
    )
    company_id = fields.Many2one(
        related="cycle_id.company_id", store=True, readonly=True
    )

    employee_id = fields.Many2one(
        "hr.employee", required=True, ondelete="restrict"
    )
    department_id = fields.Many2one(
        related="employee_id.department_id", store=True, readonly=True
    )

    grade = fields.Char(string="Grade")
    date_of_joining = fields.Date(string="Date of Joining")

    eligible = fields.Boolean(compute="_compute_policy_values", store=True)
    eligibility_reason = fields.Text(compute="_compute_policy_values", store=True)

    bonus_type = fields.Selection(
        related="cycle_id.plan_id.bonus_type", store=True, readonly=True
    )

    # Direct integration with bxi_performance_review_owl.
    q1_review_id = fields.Many2one("performance.review", readonly=True)
    q2_review_id = fields.Many2one("performance.review", readonly=True)
    q3_review_id = fields.Many2one("performance.review", readonly=True)
    q4_review_id = fields.Many2one("performance.review", readonly=True)

    q1_calibration = fields.Selection(
        related="q1_review_id.calibration", string="Q1 Calibration", readonly=True
    )
    q2_calibration = fields.Selection(
        related="q2_review_id.calibration", string="Q2 Calibration", readonly=True
    )
    q3_calibration = fields.Selection(
        related="q3_review_id.calibration", string="Q3 Calibration", readonly=True
    )
    q4_calibration = fields.Selection(
        related="q4_review_id.calibration", string="Q4 Calibration", readonly=True
    )

    final_calibration = fields.Selection(
        [
            ("5", "5 - Outstanding"),
            ("4", "4 - Exceeds Expectations"),
            ("3", "3 - Meets Expectations"),
            ("2", "2 - Needs Improvement"),
            ("1", "1 - Unsatisfactory"),
        ],
        string="Final Calibration",
        help="Final annual rating used for bonus. HR should confirm this unless the selected plan has an approved automatic aggregation rule."
    )

    target_bonus_percentage = fields.Float(
        related="cycle_id.plan_id.target_bonus_percentage", readonly=True
    )
    company_performance_factor = fields.Float(
        related="cycle_id.plan_id.company_performance_factor", readonly=True
    )

    on_payroll_on_bonus_pay_date = fields.Boolean(
        string="On Payroll on Bonus Pay Day",
        default=True,
        help="Confirm this before approval. The policy requires the employee to be on BXITech payroll on Bonus Pay Day."
    )

    lwp_days = fields.Float(
        string="LWP Days",
        compute="_compute_lwp_days",
        store=True,
    )
    lwp_factor = fields.Float(
        string="LWP Factor",
        compute="_compute_lwp_factor",
        store=True,
    )

    annual_base_salary = fields.Monetary(
        related="employee_id.bonus_annual_base",
        string="Annual Bonus Salary Basis",
        currency_field="currency_id",
        readonly=False,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id", readonly=True
    )

    rating_payout_factor = fields.Float(
        compute="_compute_bonus_amount", store=True
    )
    payout_rule_name = fields.Char(
        compute="_compute_bonus_amount", store=True
    )
    calculated_bonus = fields.Monetary(
        compute="_compute_bonus_amount",
        store=True,
        currency_field="currency_id",
    )

    _sql_constraints = [
        (
            "employee_cycle_unique",
            "unique(cycle_id, employee_id)",
            "An employee can only appear once in a bonus cycle.",
        )
    ]

    @api.model
    def _get_employee_date_of_joining(self, employee):
        """Return the DOJ already maintained on the employee master.

        The bonus module must not create a second DOJ source. Different BXI
        employee customizations have used different technical field names, so
        use the first populated field that exists on hr.employee.
        """
        for field_name in (
            "date_of_joining",
            "joining_date",
            "first_contract_date",
            "contract_start_date",
            "bonus_date_of_joining",
        ):
            if field_name in employee._fields:
                value = employee[field_name]
                if value:
                    return value
        return False

    @api.model
    def _prepare_line_vals(self, employee, cycle):
        doj = self._get_employee_date_of_joining(employee)

        return {
            "cycle_id": cycle.id,
            "employee_id": employee.id,
            "grade": employee.bonus_grade or "",
            "date_of_joining": doj,
        }

    def _quarter_ranges(self):
        """Return the four financial-year quarters for the cycle's FY.

        Bonus policy quarters are always:
            Q1 = Apr-Jun
            Q2 = Jul-Sep
            Q3 = Oct-Dec
            Q4 = Jan-Mar

        Employee DOJ must NOT shift or clip these quarters. DOJ is used for
        eligibility and DOJ-based bonus-cycle rules, while Performance Review
        periods remain aligned to the company financial year.
        """
        self.ensure_one()
        cycle = self.cycle_id
        if not cycle.date_start or not cycle.date_end:
            return {}

        # Determine the financial year containing the cycle. For an Apr-Mar FY,
        # Jan-Mar belongs to the FY that started in the previous calendar year.
        reference = cycle.date_start
        fy_year = reference.year if reference.month >= 4 else reference.year - 1

        ranges = {
            "q1": (date(fy_year, 4, 1), date(fy_year, 6, 30)),
            "q2": (date(fy_year, 7, 1), date(fy_year, 9, 30)),
            "q3": (date(fy_year, 10, 1), date(fy_year, 12, 31)),
            "q4": (date(fy_year + 1, 1, 1), date(fy_year + 1, 3, 31)),
        }

        # Only return quarters that belong to the cycle's financial year.
        # Do not clip a quarter to DOJ: a review period remains the company's
        # standard Apr-Mar quarter even when an employee joined mid-quarter.
        return {
            key: value
            for key, value in ranges.items()
            if value[1] >= cycle.date_start and value[0] <= cycle.date_end
        }

    def _find_review(self, q_start, q_end):
        """Find this employee's completed review belonging to this exact FY quarter."""
        Review = self.env["performance.review"].sudo()

        reviews = Review.search([
            ("employee_id", "=", self.employee_id.id),
            ("state", "=", "completed"),
            # The review period must be contained within this quarter.
            # This prevents a single annual/other-period review from matching
            # multiple Q1-Q4 columns.
            ("period_id.date_start", ">=", q_start),
            ("period_id.date_start", "<=", q_end),
            ("period_id.date_end", ">=", q_start),
            ("period_id.date_end", "<=", q_end),
        ])

        if not reviews:
            return Review.browse()

        # If duplicate reviews exist for the same employee/quarter, use the
        # latest completed review. Do not use a related field in SQL ORDER BY;
        # Odoo 19 rejects period_id.date_end there.
        reviews = reviews.sorted(
            key=lambda review: (
                review.period_id.date_end or fields.Date.min,
                review.id,
            ),
            reverse=True,
        )
        return reviews[:1]

    def _refresh_review_links(self):
        for line in self:
            ranges = line._quarter_ranges()
            vals = {
                "q1_review_id": False,
                "q2_review_id": False,
                "q3_review_id": False,
                "q4_review_id": False,
            }

            for quarter, (q_start, q_end) in ranges.items():
                review = line._find_review(q_start, q_end)
                vals[quarter + "_review_id"] = review.id if review else False

            line.sudo().write(vals)

    def _set_final_calibration_from_reviews(self):
        for line in self:
            mode = line.cycle_id.plan_id.rating_aggregation if line.cycle_id else "manual"
            values = [
                x for x in (
                    line.q1_review_id.calibration if line.q1_review_id else False,
                    line.q2_review_id.calibration if line.q2_review_id else False,
                    line.q3_review_id.calibration if line.q3_review_id else False,
                    line.q4_review_id.calibration if line.q4_review_id else False,
                ) if x
            ]

            if mode == "latest":
                rating = next(
                    (
                        x for x in (
                            line.q4_review_id.calibration if line.q4_review_id else False,
                            line.q3_review_id.calibration if line.q3_review_id else False,
                            line.q2_review_id.calibration if line.q2_review_id else False,
                            line.q1_review_id.calibration if line.q1_review_id else False,
                        ) if x
                    ),
                    False,
                )
                line.final_calibration = rating

            elif mode == "average" and values:
                avg = sum(float(x) for x in values) / len(values)
                line.final_calibration = str(min(5, max(1, int(round(avg)))))

            elif mode == "manual":
                # Do not invent a quarterly-to-annual formula.
                # Existing HR-entered final rating is retained.
                continue

    @api.depends(
        "employee_id.active",
        "employee_id.bonus_in_compensation",
        "employee_id.bonus_employment_type",
        "employee_id.bonus_grade",
        "employee_id.bonus_is_sales_employee",
        "employee_id.bonus_is_rebadged",
        "grade",
        "date_of_joining",
        "on_payroll_on_bonus_pay_date",
        "cycle_id.date_start",
        "cycle_id.date_end",
        "final_calibration",
    )
    def _compute_policy_values(self):
        for line in self:
            reasons = []
            employee = line.employee_id
            plan = line.cycle_id.plan_id if line.cycle_id else False

            if not employee:
                line.eligible = False
                line.eligibility_reason = "Employee not selected."
                continue

            if not employee.active:
                reasons.append("Employee is inactive.")

            if employee.bonus_employment_type not in ("permanent", "fte"):
                reasons.append("Employee is not marked as Permanent/FTE.")

            if not employee.bonus_in_compensation:
                reasons.append("Performance bonus is not included in compensation.")

            expected_geography = {
                "yepb": "india",
                "ogpb": "europe_apac_row",
                "ogsm": "americas_canada",
            }.get(plan.bonus_type if plan else False)

            if expected_geography and employee.bonus_geography != expected_geography:
                reasons.append("Employee geography does not match the selected bonus plan.")

            grade = (line.grade or "").upper().strip()
            allowed_grades = {
                x.strip().upper()
                for x in (plan.applicable_grades or "").split(",")
                if x.strip()
            }
            if grade not in allowed_grades:
                reasons.append("Grade is outside the configured eligible E0-E3 grades.")

            if employee.bonus_is_sales_employee:
                reasons.append("Employee is covered by Sales Incentive Policy.")

            if employee.bonus_is_rebadged:
                reasons.append("Employee is rebadged and governed by a separate bonus plan.")

            if not line.date_of_joining:
                reasons.append("Date of Joining is not configured.")
            elif line.date_of_joining > line.cycle_id.date_end:
                reasons.append("Date of Joining is after the bonus cycle.")

            if not line.on_payroll_on_bonus_pay_date:
                reasons.append("Employee is not on payroll on Bonus Pay Day.")

            if not line.final_calibration:
                reasons.append("Final performance calibration is not available.")

            line.eligible = not reasons
            line.eligibility_reason = "Eligible" if line.eligible else " ".join(reasons)

    @api.depends("employee_id", "cycle_id.date_start", "cycle_id.date_end")
    def _compute_lwp_days(self):
        has_leave = "hr.leave" in self.env
        Leave = self.env["hr.leave"].sudo() if has_leave else False

        for line in self:
            total = 0.0
            if Leave and line.employee_id and line.cycle_id:
                leaves = Leave.search([
                    ("employee_id", "=", line.employee_id.id),
                    ("state", "=", "validate"),
                    ("request_date_from", "<=", line.cycle_id.date_end),
                    ("request_date_to", ">=", line.cycle_id.date_start),
                ])
                for leave in leaves:
                    name = (leave.holiday_status_id.name or "").lower()
                    code = (getattr(leave.holiday_status_id, "code", False) or "").lower()
                    if "lwp" in name or "leave without pay" in name or code == "lwp":
                        total += leave.number_of_days
            line.lwp_days = total

    @api.depends(
        "lwp_days",
        "cycle_id.date_start",
        "cycle_id.date_end",
        "cycle_id.plan_id.include_lwp_adjustment",
    )
    def _compute_lwp_factor(self):
        for line in self:
            if not line.cycle_id.plan_id.include_lwp_adjustment:
                line.lwp_factor = 1.0
                continue

            if not line.cycle_id.date_start or not line.cycle_id.date_end:
                line.lwp_factor = 1.0
                continue

            cycle_days = (line.cycle_id.date_end - line.cycle_id.date_start).days + 1
            line.lwp_factor = max(0.0, 1.0 - (line.lwp_days / cycle_days))

    @api.depends(
        "eligible",
        "final_calibration",
        "target_bonus_percentage",
        "company_performance_factor",
        "annual_base_salary",
        "lwp_factor",
        "cycle_id.plan_id.rating_rule_ids",
    )
    def _compute_bonus_amount(self):
        for line in self:
            line.rating_payout_factor = 0.0
            line.payout_rule_name = False
            line.calculated_bonus = 0.0

            if not line.eligible or not line.final_calibration:
                continue

            rating = float(line.final_calibration)
            rules = line.cycle_id.plan_id.rating_rule_ids.sorted(
                key=lambda r: (r.sequence, r.min_rating)
            )
            rule = rules.filtered(
                lambda r: r.min_rating <= rating <= r.max_rating
            )[:1]
            if not rule:
                continue

            line.rating_payout_factor = rule.payout_factor
            line.payout_rule_name = rule.name
            line.calculated_bonus = (
                line.annual_base_salary
                * (line.target_bonus_percentage / 100.0)
                * line.rating_payout_factor
                * line.company_performance_factor
                * line.lwp_factor
            )

    def action_refresh_from_performance_review(self):
        self._refresh_review_links()
        self._set_final_calibration_from_reviews()
        self._compute_policy_values()
        self._compute_lwp_days()
        self._compute_lwp_factor()
        self._compute_bonus_amount()
        return True
