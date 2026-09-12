from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
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

    @api.constrains(
        'holiday_status_id',
        'request_date_from',
        'request_date_to'
    )
    def _check_el_leave_rules(self):
        """
        Enforce EL (Earned Leave) application window:
        EL must normally be applied at least 7 days before
        the leave start date.
        Automatic EL conversion from Sick Leave is exempted
        from this advance-notice rule.
        """
        for rec in self:
            if self.env.context.get('skip_el_advance_check'):
                continue

            if not rec.holiday_status_id:
                continue

            code = (
                getattr(rec.holiday_status_id, 'time_off_code', False)
                or getattr(rec.holiday_status_id, 'leave_code', False)
                or getattr(rec.holiday_status_id, 'code', False)
                or ''
            ).strip().upper()

            if code != 'EL':
                continue

            if rec.request_date_from:
                try:
                    days_diff = (
                        rec.request_date_from - date.today()
                    ).days

                    if days_diff < 7:
                        raise ValidationError(
                            _(
                                "EL leave must be applied at least "
                                "7 days before the leave start date."
                            )
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


    sick_leave_policy = fields.Boolean(
        string="Sick Leave Policy",
        compute="_compute_sick_leave_policy",
    )

    @api.depends("holiday_status_id")
    def _compute_sick_leave_policy(self):
        for leave in self:
            leave.sick_leave_policy = (
                (leave.holiday_status_id.leave_code or "").strip().upper()
                == "SICK"
            )

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    def _get_leave_type_by_code(self, code):
        """Return the configured leave type for the current company."""
        hr_type = self.env["hr.leave.type"]

        # Build a safe domain depending on which identifying fields exist
        fields = hr_type._fields

        if "time_off_code" in fields and "leave_code" in fields:
            domain = [
                "|",
                ("time_off_code", "=", code),
                ("leave_code", "=", code),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", self.env.company.id),
            ]
        elif "time_off_code" in fields:
            domain = [
                ("time_off_code", "=", code),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", self.env.company.id),
            ]
        elif "leave_code" in fields:
            domain = [
                ("leave_code", "=", code),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", self.env.company.id),
            ]
        else:
            # Fallback: search by name (case-insensitive contains)
            return hr_type.search(
                [
                    ("name", "ilike", code),
                    "|",
                    ("company_id", "=", False),
                    ("company_id", "=", self.env.company.id),
                ],
                limit=1,
            )

        return hr_type.search(domain, limit=1)

    def _get_el_balance(self, employee, date_from=None):
        """
        Return the employee's current EL virtual remaining balance.

        Odoo 19 uses allocation data / virtual_remaining_leaves
        for available time-off calculations.
        """
        el_type = self._get_leave_type_by_code("EL")

        if not el_type:
            raise ValidationError(
                _(
                    "Earned Leave (EL) time off type is not configured.\n"
                    "Please configure a Time Off Type with code EL."
                )
            )

        date_from = date_from or fields.Date.context_today(self)

        allocation_data = el_type.get_allocation_data(
            employee,
            date_from,
        )

        if not allocation_data:
            return 0.0

        employee_data = allocation_data.get(employee)

        if not employee_data:
            return 0.0

        total_balance = 0.0

        for item in employee_data:
            # item may be a (allocation, values) tuple, or a dict-like structure
            allocation = None
            allocation_values = None

            if isinstance(item, (list, tuple)):
                if len(item) >= 2:
                    allocation, allocation_values = item[0], item[1]
                else:
                    continue
            elif isinstance(item, dict):
                allocation_values = item
                allocation = item.get("allocation") or item.get("allocation_id")
            else:
                # unknown structure, skip
                continue

            if allocation:
                if (not getattr(allocation, 'date_to', None)
                        or allocation.date_to >= date_from):
                    total_balance += allocation_values.get(
                        "virtual_remaining_leaves",
                        0.0,
                    )

        return max(total_balance, 0.0)

    def _get_working_days_between(self, employee, date_from, date_to):
        """
        Return working dates between two dates according to
        the employee's working calendar.
        """
        calendar = employee.resource_calendar_id

        if not calendar:
            calendar = self.env.company.resource_calendar_id

        if not calendar:
            return []

        start_datetime = fields.Datetime.to_datetime(date_from)
        end_datetime = fields.Datetime.to_datetime(date_to) + timedelta(
            days=1
        )

        work_data = employee._get_work_days_data(
            start_datetime,
            end_datetime,
        )

        return work_data

    # ---------------------------------------------------------
    # Validation
    # ---------------------------------------------------------

    def _check_sick_leave_policy(self):
        """
        Apply the BXI Sick Leave policy.

        Rules:
            1. Sick Leave requires EL balance.
            2. Available EL is consumed first.
            3. If EL is insufficient, remaining days become LWP.
            4. If no EL is available, entire request becomes LWP.
            5. Sick Leave > 1 day requires attachment.
            6. Automatic EL conversion bypasses the normal
            EL advance-notice validation.
        """

        # Prevent recursive processing when this method itself creates
        # an LWP record.
        if self.env.context.get('skip_sick_leave_policy'):
            return

        for leave in self:

            if not leave.employee_id:
                continue

            # ---------------------------------------------------------
            # Identify Sick Leave
            # ---------------------------------------------------------

            leave_code = (
                getattr(leave.holiday_status_id, 'code', False)
                or getattr(leave.holiday_status_id, 'leave_code', False)
                or getattr(leave.holiday_status_id, 'time_off_code', False)
                or ''
            ).strip().upper()

            if leave_code != 'SICK':
                continue

            # ---------------------------------------------------------
            # Attachment requirement
            # ---------------------------------------------------------

            req_days = float(leave.number_of_days or 0.0)

            if req_days > 1:
                has_attachment = bool(leave.attachment_ids)
                if 'supported_attachment_ids' in leave._fields:
                    has_attachment = (
                        has_attachment
                        or bool(leave.supported_attachment_ids)
                    )
                if not has_attachment:
                    raise ValidationError(
                        _(
                            "Attachment Required\n\n"
                            "Sick Leave for more than 1 day requires "
                            "supporting documentation.\n\n"
                            "Please attach the required document before "
                            "submitting the request."
                        )
                    )

            if req_days <= 0:
                continue

            if not leave.request_date_from or not leave.request_date_to:
                continue

            # ---------------------------------------------------------
            # Get EL and LWP leave types
            # ---------------------------------------------------------

            el_type = self._get_leave_type_by_code("EL")
            lwp_type = self._get_leave_type_by_code("LWP")

            if not el_type:
                raise ValidationError(
                    _(
                        "Earned Leave (EL) time off type is not configured.\n"
                        "Please configure a Time Off Type with code EL."
                    )
                )

            if not lwp_type:
                raise ValidationError(
                    _(
                        "LWP time off type is not configured.\n"
                        "Please configure a Time Off Type with code LWP."
                    )
                )

            # ---------------------------------------------------------
            # Get current EL balance
            # ---------------------------------------------------------

            el_balance = self._get_el_balance(
                leave.employee_id,
                leave.request_date_from,
            )

            # We only consume complete EL days.
            usable_el_days = min(
                int(el_balance),
                int(req_days)
            )

            # ---------------------------------------------------------
            # CASE 1:
            # No EL available -> Entire Sick Leave becomes LWP
            # ---------------------------------------------------------

            if usable_el_days <= 0:

                leave.with_context(
                    skip_sick_leave_policy=True
                ).write({
                    'holiday_status_id': lwp_type.id,
                })

                continue

            # ---------------------------------------------------------
            # Save ORIGINAL dates before changing the current leave
            # ---------------------------------------------------------

            original_start_date = leave.request_date_from
            original_end_date = leave.request_date_to
            original_name = leave.name or _('Sick Leave')

            # ---------------------------------------------------------
            # CASE 2:
            # EL fully covers Sick Leave
            #
            # Example:
            # Sick = 3 days
            # EL    = 3 days
            #
            # Result:
            # 3 days EL
            # ---------------------------------------------------------

            if usable_el_days >= req_days:

                leave.with_context(
                    skip_sick_leave_policy=True,
                    skip_el_advance_check=True,
                ).write({
                    'holiday_status_id': el_type.id,
                })

                continue

            # ---------------------------------------------------------
            # CASE 3:
            # Partial EL + LWP
            #
            # Example:
            # Sick = 3
            # EL   = 1
            #
            # Result:
            # Day 1 = EL
            # Day 2 = LWP
            # Day 3 = LWP
            # ---------------------------------------------------------

            el_days = usable_el_days
            lwp_days = req_days - el_days

            # ---------------------------------------------------------
            # Calculate date ranges
            # ---------------------------------------------------------

            el_start_date = original_start_date

            el_end_date = (
                el_start_date
                + timedelta(days=el_days - 1)
            )

            lwp_start_date = el_end_date + timedelta(days=1)
            lwp_end_date = original_end_date

            # ---------------------------------------------------------
            # Update ORIGINAL record to EL
            # ---------------------------------------------------------

            leave.with_context(
                skip_sick_leave_policy=True,
                skip_el_advance_check=True,
            ).write({
                'holiday_status_id': el_type.id,
                'request_date_from': el_start_date,
                'request_date_to': el_end_date,
                'number_of_days': el_days,
            })

            # ---------------------------------------------------------
            # Create remaining LWP record
            # ---------------------------------------------------------

            lwp_vals = {
                'name': (
                    f"{original_name} (LWP)"
                ),
                'employee_id': leave.employee_id.id,
                'holiday_status_id': lwp_type.id,
                'request_date_from': lwp_start_date,
                'request_date_to': lwp_end_date,
                'number_of_days': lwp_days,
                'company_id': leave.company_id.id,
            }

            # ---------------------------------------------------------
            # Copy attachments to LWP if available
            # ---------------------------------------------------------

            if leave.attachment_ids:
                lwp_vals['attachment_ids'] = [
                    (6, 0, leave.attachment_ids.ids)
                ]

            self.env['hr.leave'].with_context(
                skip_sick_leave_policy=True
            ).create(lwp_vals)

    @api.model_create_multi
    def create(self, vals_list):

        leaves = super().create(vals_list)

        if not self.env.context.get('skip_sick_leave_policy'):
            leaves._check_sick_leave_policy()

        return leaves

    # ---------------------------------------------------------
    # Write
    # ---------------------------------------------------------

    def write(self, vals):

        result = super().write(vals)

        fields_to_check = {
            "employee_id",
            "holiday_status_id",
            "request_date_from",
            "request_date_to",
            "attachment_ids",
            "supported_attachment_ids",
        }

        if (
            fields_to_check.intersection(vals)
            and not self.env.context.get('skip_sick_leave_policy')
        ):
            self._check_sick_leave_policy()

        return result