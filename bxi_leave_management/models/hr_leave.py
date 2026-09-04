from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date, timedelta


class HrEmployeeLeave(models.Model):
    _inherit = 'hr.leave'

    is_submission_email_sent = fields.Boolean(
        string="Submission Email Sent",
        default=False,
        copy=False
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._check_and_send_leave_notification()
        return records

    def write(self, vals):
        res = super().write(vals)
        for rec in self:
            rec._check_and_send_leave_notification()
        return res

    def action_confirm(self):
        res = super().action_confirm()
        for rec in self:
            rec._check_and_send_leave_notification()
        return res

    def _check_and_send_leave_notification(self):
        for rec in self:
            if rec.is_submission_email_sent:
                continue
            if rec.state not in ('draft', 'cancel', 'refuse'):
                rec._send_leave_submission_email()

    def _send_leave_submission_email(self):
        template = self.env.ref(
            'bxi_leave_management.email_template_leave_request_submitted',
            raise_if_not_found=False
        )
        if not template:
            return
        for rec in self:
            if rec.is_submission_email_sent:
                continue

            recipients = ['hr@bxitech.com']

            manager = rec.employee_id.parent_id or rec.employee_id.leave_manager_id
            manager_email = False
            if manager:
                manager_email = manager.work_email or (manager.user_id and manager.user_id.email)

            if manager_email:
                recipients.append(manager_email.strip())

            unique_recipients = list(dict.fromkeys([r for r in recipients if r]))
            email_to_str = ','.join(unique_recipients)

            rec.sudo().write({'is_submission_email_sent': True})

            template.sudo().send_mail(
                rec.id,
                email_values={'email_to': email_to_str},
                force_send=True
            )

    @api.constrains('holiday_status_id', 'request_date_from', 'request_date_to')
    def _check_rh_leave_rules(self):
        for rec in self:

            # Apply only for RH
            if not rec.holiday_status_id or rec.holiday_status_id.time_off_code != 'RH':
                continue

            # =========================
            # RULE 1: ONLY 1 DAY
            # =========================
            if rec.request_date_from != rec.request_date_to:
                raise ValidationError("RH leave can only be applied for 1 day.")

            # =========================
            # RULE 2: ONLY OPTIONAL HOLIDAY DATE
            # =========================
            optional_holiday = self.env['l10n.in.hr.leave.optional.holiday'].search([
                ('date', '=', rec.request_date_from),
                ('company_id', '=', rec.company_id.id)
            ], limit=1)

            if not optional_holiday:
                raise ValidationError(
                    "RH leave can only be applied on Optional Holiday dates."
                )

            # =========================
            # RULE 3: ADVANCE NOTICE (RH)
            # RH must be applied at least 3 days before the leave date.
            # =========================
            if rec.request_date_from:
                try:
                    days_diff = (rec.request_date_from - date.today()).days
                    if days_diff < 3:
                        raise ValidationError(
                            "RH leave must be applied at least 3 days before the leave date.You can apply for LWP for the same."
                        )
                except TypeError:
                    # If dates are invalid or None, let other validations handle it
                    pass

    @api.constrains('holiday_status_id', 'request_date_from', 'request_date_to')
    def _check_el_leave_rules(self):
        """
        Enforce EL (Earned Leave) application window: must be applied at least 7 days before.
        This runs in addition to any other constraints.
        """
        for rec in self:
            if not rec.holiday_status_id or rec.holiday_status_id.time_off_code != 'EL':
                continue

            if rec.request_date_from:
                try:
                    days_diff = (rec.request_date_from - date.today()).days
                    if days_diff < 7:
                        raise ValidationError(
                            "EL leave must be applied at least 7 days before the leave start date.You can apply for LWP for the same."
                        )
                except TypeError:
                    pass

        @api.constrains('holiday_status_id', 'request_date_from', 'request_date_to')
        def _check_ml_sl_al_rules(self):
            """
            Enforce advance notice rules for Maternity (ML), Surrogacy (SL), and Adoption (AL):
            - ML: at least 60 days (approx. 2 months) before start
            - SL: at least 28 days before start
            - AL: at least 28 days before start
            """
            for rec in self:
                if not rec.holiday_status_id or not rec.request_date_from:
                    continue
                code = getattr(rec.holiday_status_id, 'time_off_code', False) or ''
                code = (code or '').strip().upper()

                try:
                    days_diff = (rec.request_date_from - date.today()).days
                except Exception:
                    days_diff = None

                if code == 'ML':
                    if days_diff is None or days_diff < 60:
                        raise ValidationError(
                            "Maternity Leave (ML) must be applied at least 2 months (60 days) before the leave start date."
                        )

                if code == 'SL':
                    if days_diff is None or days_diff < 28:
                        raise ValidationError(
                            "Surrogacy Leave (SL) must be applied at least 4 weeks (28 days) before the leave start date."
                        )

                if code == 'AL':
                    if days_diff is None or days_diff < 28:
                        raise ValidationError(
                            "Adoption Leave (AL) must be applied at least 4 weeks (28 days) before the leave start date."
                        )


    compensation_required = fields.Boolean(
        string="Compensation Required",
        compute="_compute_compensation_required",
        store=True,
        readonly=True,
    )

    compensation_date = fields.Date(
        string="Compensation Date",
        help=(
            "For Earned Leave taken on Tuesday, Wednesday or Thursday, "
            "select Monday or Friday of the same week as the compensation date."
        ),
    )


    @api.depends("employee_id", "request_date_from", "holiday_status_id")
    def _compute_compensation_required(self):
        for leave in self:
            leave.compensation_required = (
                leave._is_earned_leave()
                and leave._is_mandatory_wfo_day()
            )

    def _is_earned_leave(self):
        """Return True when the leave type is Earned Leave."""
        self.ensure_one()
        leave_type = self.holiday_status_id
        code = (
            getattr(leave_type, "code", False)
            or getattr(leave_type, "leave_code", False)
        )
        if code:
            return code.upper() == "EL"
        return (leave_type.name or "").strip().upper() in (
            "EL",
            "EARNED LEAVE",
        )

    def _is_mandatory_wfo_day(self):
        """
        Tuesday = 1
        Wednesday = 2
        Thursday = 3

        Monday = 0
        Friday = 4
        """
        self.ensure_one()

        if not self.request_date_from:
            return False

        return self.request_date_from.weekday() in (1, 2, 3)

    # ==========================================================
    # EMPLOYEE WEEKDAY LOCATION
    # ==========================================================

    def _get_employee_day_location(self, employee, check_date):
        """Return the employee's configured location for a particular day."""

        weekday_location_fields = {
            0: "monday_location_id",
            1: "tuesday_location_id",
            2: "wednesday_location_id",
            3: "thursday_location_id",
            4: "friday_location_id",
            5: "saturday_location_id",
            6: "sunday_location_id",
        }

        field_name = weekday_location_fields.get(check_date.weekday())

        if not field_name:
            return False

        if field_name not in employee._fields:
            return False

        return employee[field_name]


    def _validate_compensation_date(self):
        for leave in self:

            if not leave.compensation_required:
                continue

            if not leave.compensation_date:
                raise ValidationError(
                    _(
                        "Compensation is required because you are applying "
                        "Earned Leave on a mandatory WFO day. "
                        "Please select a compensation date."
                    )
                )

            leave_date = leave.request_date_from
            compensation_date = leave.compensation_date

            # --------------------------------------------------
            # Same week
            # --------------------------------------------------

            monday = leave_date - timedelta(days=leave_date.weekday())
            sunday = monday + timedelta(days=6)

            if not (monday <= compensation_date <= sunday):
                raise ValidationError(
                    _(
                        "The compensation date must be within the same "
                        "week as the Earned Leave."
                    )
                )

            # --------------------------------------------------
            # Only Monday or Friday
            # --------------------------------------------------

            if compensation_date.weekday() not in (0, 4):
                raise ValidationError(
                    _(
                        "For Earned Leave taken on Tuesday, Wednesday or "
                        "Thursday, compensation can only be completed on "
                        "Monday or Friday of the same week."
                    )
                )

            # --------------------------------------------------
            # Cannot be same as leave date
            # --------------------------------------------------

            if compensation_date == leave_date:
                raise ValidationError(
                    _("The compensation date cannot be the leave date.")
                )

            # --------------------------------------------------
            # Employee must have a WFO location on compensation date
            # --------------------------------------------------

            compensation_location = leave._get_employee_day_location(
                leave.employee_id,
                compensation_date,
            )

            if not compensation_location:
                raise ValidationError(
                    _(
                        "No work location is configured for %s on %s. "
                        "Please configure the employee's work location "
                        "before selecting this compensation date."
                    )
                    % (
                        leave.employee_id.name,
                        compensation_date,
                    )
                )

            # --------------------------------------------------
            # Compensation date cannot itself be leave
            # --------------------------------------------------

            existing_leave = self.env["hr.leave"].search(
                [
                    ("employee_id", "=", leave.employee_id.id),
                    ("id", "!=", leave.id),
                    ("state", "not in", ("cancel", "refuse")),
                    ("request_date_from", "<=", compensation_date),
                    ("request_date_to", ">=", compensation_date),
                ],
                limit=1,
            )

            if existing_leave:
                raise ValidationError(
                    _(
                        "The selected compensation date %s already has "
                        "a leave request for %s. Please select another "
                        "compensation date."
                    )
                    % (
                        compensation_date,
                        leave.employee_id.name,
                    )
                )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._validate_compensation_date()
        return records


    def write(self, vals):
        result = super().write(vals)
        self._validate_compensation_date()
        return result

    def action_confirm(self):
        for leave in self:
            leave._validate_compensation_date()
        return super().action_confirm()