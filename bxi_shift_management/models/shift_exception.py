# -*- coding: utf-8 -*-

import json
import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


_logger = logging.getLogger(__name__)

# Single-day requests that regularize the attendance of the day.
REGULARIZATION_CATEGORIES = (
    "attendance_regularization",
    "missing_timesheet",
    "late_checkout",
)


class BxiShiftException(models.Model):
    _name = "bxi.shift.exception"
    _description = "Exception Working Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        readonly=True,
        default="New",
        tracking=True,
    )

    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,
        default=lambda self: self._default_employee_id(),
        tracking=True,
    )

    manager_id = fields.Many2one(
        "hr.employee",
        string="Manager",
        related="employee_id.parent_id",
        tracking=True,
    )

    is_request_manager = fields.Boolean(
        string="Is Request Manager",
        compute="_compute_is_request_manager",
    )

    @api.depends('manager_id')
    def _compute_is_request_manager(self):
        current_user = self.env.user
        for record in self:
            record.is_request_manager = (
                record.manager_id.user_id == current_user
            )

    can_hr_approve = fields.Boolean(
        string="Can HR Approve",
        compute="_compute_can_hr_approve",
    )

    def _compute_can_hr_approve(self):
        is_hr = self.env.user.has_group("bxi_shift_management.group_shift_hr")
        for record in self:
            record.can_hr_approve = is_hr

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        tracking=True,
    )

    category = fields.Selection(
        [
            ("exception", "Exception"),
            ("missing_timesheet", "Missing Timesheet"),
            ("late_checkout", "Late Checkout"),
            ("attendance_regularization", "Attendance Regularization"),
        ],
        string="Category",
        default="exception",
        required=True,
        tracking=True,
    )

    is_regularization = fields.Boolean(
        string="Is Regularization",
        compute="_compute_is_regularization",
        store=True,
    )

    regularize_check_in = fields.Float(
        string="Check-in Time",
        tracking=True,
        help="Actual check-in time of the exception date (local time).",
    )

    regularize_check_out = fields.Float(
        string="Check-out Time",
        tracking=True,
        help="Actual check-out time of the exception date (local time).",
    )

    regularized_shift_hours = fields.Float(
        string="Regularized Shift Hours",
        digits=(10, 2),
        readonly=True,
        copy=False,
        help=(
            "Time between the regularized check-in and check-out within "
            "the shift, lunch break included. Counted in the shift wise "
            "production hours once approved."
        ),
    )

    attendance_id = fields.Many2one(
        "hr.attendance",
        string="Regularized Attendance",
        readonly=True,
        copy=False,
    )

    attendance_created = fields.Boolean(
        string="Attendance Created by Regularization",
        readonly=True,
        copy=False,
    )

    attendance_original_check_in = fields.Datetime(
        string="Original Check-in",
        readonly=True,
        copy=False,
        help="Check-in of the attendance before the regularization.",
    )

    attendance_original_check_out = fields.Datetime(
        string="Original Check-out",
        readonly=True,
        copy=False,
        help="Check-out of the attendance before the regularization.",
    )

    @api.depends("category")
    def _compute_is_regularization(self):
        for record in self:
            record.is_regularization = (
                record.category in REGULARIZATION_CATEGORIES
            )

    date_from = fields.Date(
        string="From Date",
        required=True,
        tracking=True,
    )

    date_to = fields.Date(
        string="To Date",
        required=True,
        tracking=True,
    )

    wfh_day_count = fields.Integer(
        string="WFH Days",
        compute="_compute_wfh_day_count",
        store=True,
    )

    show_compensation_date = fields.Boolean(
        string="Show Compensation Date",
        compute="_compute_wfh_day_count",
        store=True,
    )

    show_compensation_date_2 = fields.Boolean(
        string="Show Compensation Date 2",
        compute="_compute_wfh_day_count",
        store=True,
    )

    show_compensation_date_3 = fields.Boolean(
        string="Show Compensation Date 3",
        compute="_compute_wfh_day_count",
        store=True,
    )

    to_location_id = fields.Many2one(
        "hr.work.location",
        string="To Work Location",
    )

    new_calendar_id = fields.Many2one(
        "resource.calendar",
        string="New Working Schedule",
    )

    compensation_date = fields.Date(
        string="Compensation Date",
        tracking=True,
        help=(
            "For Home/WFH exception working, compensation must be on "
            "Monday or Friday and within 7 calendar days before or "
            "after the exception date."
        ),
    )
    compensation_date_2 = fields.Date(
        string="Compensation Date 2",
        tracking=True,
        help="Second compensation date for multi-day Home/WFH requests.",
    )

    compensation_date_3 = fields.Date(
        string="Compensation Date 3",
        tracking=True,
        help="Third compensation date for multi-day Home/WFH requests.",
    )

    mode = fields.Selection(
        [
            ("office", "Office"),
            ("home", "Home"),
            ("client", "Client Site"),
        ],
        string="Mode",
        tracking=True,
    )
    allowed_weekdays = fields.Char(
        string="Allowed Weekdays",
        help=(
            "Comma-separated weekday numbers with Monday=0 and "
            "Sunday=6. Example: 1,2,3"
        ),
        tracking=True,
    )
    client_location = fields.Char(
        string="Client Location",
    )
    client_name = fields.Char(
        string="Client Name",
    )

    reason = fields.Text(
        string="Reason / Description",
    )

    @api.depends("date_from", "date_to", "mode")
    def _compute_wfh_day_count(self):
        for record in self:
            record.wfh_day_count = 0
            record.show_compensation_date = False
            record.show_compensation_date_2 = False
            record.show_compensation_date_3 = False

            if (
                record.mode != "home"
                or not record.date_from
                or not record.date_to
                or record.date_to < record.date_from
            ):
                continue

            if record.date_from == record.date_to:
                if record.date_from.weekday() in (1, 2, 3):
                    record.wfh_day_count = 1
                    record.show_compensation_date = True
            
    @api.onchange("mode", "date_from", "date_to")
    def _onchange_wfh_dates(self):
        for record in self:

            if record.mode != "home":
                record.compensation_date = False
                record.compensation_date_2 = False
                record.compensation_date_3 = False
                continue

            # Home/WFH is exactly one day.
            if record.date_from and record.date_to:
                if record.date_from != record.date_to:
                    record.compensation_date = False

                # Only one compensation date is allowed.
                record.compensation_date_2 = False
                record.compensation_date_3 = False

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("manager_approval", "Manager Approval"),
            # Second level, regularization categories only.
            ("hr_approval", "HR Approval"),
            ("approved", "Approved"),
            ("refused", "Refused"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
        copy=False,
    )

    manager_remark = fields.Text(
        string="Manager Remark",
        tracking=True,
    )

    manager_approved_by = fields.Many2one(
        "hr.employee",
        string="Manager Approved By",
        related="employee_id.parent_id",
        readonly=True,
        copy=False,
        tracking=True,
    )

    manager_approved_date = fields.Datetime(
        string="Manager Approved On",
        readonly=True,
        copy=False,
        tracking=True,
    )

    hr_remark = fields.Text(
        string="HR Remark",
        tracking=True,
    )

    hr_approved_by = fields.Many2one(
        "hr.employee",
        string="HR Approved By",
        readonly=True,
        copy=False,
        tracking=True,
    )

    hr_approved_date = fields.Datetime(
        string="HR Approved On",
        readonly=True,
        copy=False,
        tracking=True,
    )

    original_weekday_locations = fields.Text(
        string="Original Weekday Locations",
        copy=False,
    )

    @api.model
    def _default_employee_id(self):
        employee = self.env["hr.employee"].search(
            [
                ("user_id", "=", self.env.user.id),
            ],
            limit=1,
        )
        return employee.id or False

    @api.onchange("category", "date_from")
    def _onchange_regularization(self):
        for record in self:
            if record.category not in REGULARIZATION_CATEGORIES:
                continue
            record.date_to = record.date_from
            record.update(record._get_regularization_cleared_values())
            # Only the times of the category are entered.
            if record.category != "attendance_regularization":
                record.regularize_check_in = 0.0
            if record.category == "missing_timesheet":
                record.regularize_check_out = 0.0

    @api.model
    def _get_regularization_cleared_values(self):
        """Exception-only values that a regularization request never has."""
        return {
            "mode": False,
            "to_location_id": False,
            "new_calendar_id": False,
            "allowed_weekdays": False,
            "compensation_date": False,
            "compensation_date_2": False,
            "compensation_date_3": False,
        }

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        for record in self:
            if record.employee_id:
                record.manager_id = record.employee_id.parent_id or False
                record.company_id = (
                    record.employee_id.company_id
                    or self.env.company
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault(
                "name",
                self.env["ir.sequence"].sudo().next_by_code(
                    "bxi.shift.exception"
                )
                or "/",
            )

            employee_id = vals.get("employee_id")
            if employee_id:
                employee = (
                    self.env["hr.employee"]
                    .browse(employee_id)
                    .exists()
                )

                if employee:
                    vals.setdefault(
                        "manager_id",
                        employee.parent_id.id or False,
                    )

                    vals.setdefault(
                        "company_id",
                        employee.company_id.id
                        or self.env.company.id,
                    )

            # A regularization is for the single Exception Date.
            if vals.get("category") in REGULARIZATION_CATEGORIES:
                vals["date_to"] = vals.get("date_from")
                vals.update(self._get_regularization_cleared_values())

        records = super().create(vals_list)

        return records

    def write(self, vals):
        if "date_from" not in vals and "category" not in vals:
            return super().write(vals)

        regularizations = self.filtered(
            lambda rec: vals.get("category", rec.category)
            in REGULARIZATION_CATEGORIES
        )

        # date_to follows date_from in the same write, otherwise the
        # date order constraint fails before it can be synced.
        for record in regularizations:
            record_vals = dict(
                vals,
                date_to=vals.get("date_from", record.date_from),
            )
            if "category" in vals:
                record_vals.update(self._get_regularization_cleared_values())
            super(BxiShiftException, record).write(record_vals)

        others = self - regularizations
        if others:
            super(BxiShiftException, others).write(vals)
        return True

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for record in self:
            if (
                record.date_from
                and record.date_to
                and record.date_to < record.date_from
            ):
                raise ValidationError(
                    _("To Date cannot be earlier than From Date.")
                )

    def _get_wfh_dates(self):
        """
        Return the WFH date.
        Home/WFH is strictly limited to one day.
        Allowed weekdays:
            Tuesday
            Wednesday
            Thursday
        """
        self.ensure_one()
        if not self.date_from or not self.date_to:
            return []

        if self.mode != "home":
            return []

        if self.date_from != self.date_to:
            return []

        if self.date_from.weekday() not in (1, 2, 3):
            return []

        return [self.date_from]

    def _get_compensation_dates(self):
        """
        Return the single compensation date for a Home/WFH request.
        """
        self.ensure_one()
        return [
            self.compensation_date
        ] if self.compensation_date else []

    def _validate_wfh_policy(self):
        """
        Validate Home/WFH exception policy.

        Rules:
            - Home/WFH request must be exactly ONE day.
            - Home/WFH is allowed only Tuesday, Wednesday or Thursday.
            - Exactly ONE compensation date is required.
            - Compensation date must be Monday or Friday.
            - Compensation date must be within +/- 7 calendar days.
            - Compensation date cannot equal the WFH date.
            - compensation_date_2 and compensation_date_3 are not allowed.
        """

        for record in self:

            if record.mode != "home" or record.is_regularization:
                continue

            # ---------------------------------------------------------
            # Basic dates
            # ---------------------------------------------------------
            if not record.date_from or not record.date_to:
                raise ValidationError(
                    _(
                        "From Date and To Date are required "
                        "for Work From Home."
                    )
                )

            # ---------------------------------------------------------
            # Home/WFH must be exactly ONE day
            # ---------------------------------------------------------
            if record.date_from != record.date_to:
                raise ValidationError(
                    _(
                        "Work From Home can be requested for only ONE day.\n\n"
                        "From Date: %(date_from)s\n"
                        "To Date: %(date_to)s\n\n"
                        "Please select the same date in From Date and To Date."
                    )
                    % {
                        "date_from": record.date_from,
                        "date_to": record.date_to,
                    }
                )

            wfh_date = record.date_from

            # ---------------------------------------------------------
            # WFH allowed only Tuesday / Wednesday / Thursday
            # ---------------------------------------------------------
            if wfh_date.weekday() not in (1, 2, 3):
                raise ValidationError(
                    _(
                        "Work From Home is allowed only on "
                        "Tuesday, Wednesday or Thursday.\n\n"
                        "Selected Date: %(date)s"
                    )
                    % {
                        "date": wfh_date,
                    }
                )

            # ---------------------------------------------------------
            # Exactly ONE compensation date
            # ---------------------------------------------------------
            compensation_dates = record._get_compensation_dates()

            if len(compensation_dates) != 1:
                raise ValidationError(
                    _(
                        "Exactly ONE compensation date is required "
                        "for a one-day Work From Home request."
                    )
                )

            # ---------------------------------------------------------
            # Second and third compensation dates are NOT allowed
            # ---------------------------------------------------------
            if record.compensation_date_2:
                raise ValidationError(
                    _(
                        "Only ONE compensation date is allowed "
                        "for Work From Home."
                    )
                )

            if record.compensation_date_3:
                raise ValidationError(
                    _(
                        "Only ONE compensation date is allowed "
                        "for Work From Home."
                    )
                )

            compensation_date = record.compensation_date

            # ---------------------------------------------------------
            # Compensation cannot equal WFH date
            # ---------------------------------------------------------
            if compensation_date == wfh_date:
                raise ValidationError(
                    _(
                        "Compensation Date cannot be the same as "
                        "the Work From Home date."
                    )
                )

            # ---------------------------------------------------------
            # Compensation must be Monday or Friday
            # ---------------------------------------------------------
            if compensation_date.weekday() not in (0, 4):
                raise ValidationError(
                    _(
                        "Invalid Compensation Date: %(date)s.\n\n"
                        "Compensation must be on Monday or Friday."
                    )
                    % {
                        "date": compensation_date,
                    }
                )

            # ---------------------------------------------------------
            # Compensation must be within +/- 7 calendar days
            # ---------------------------------------------------------
            allowed_start = wfh_date - timedelta(days=7)
            allowed_end = wfh_date + timedelta(days=7)

            if not (
                allowed_start
                <= compensation_date
                <= allowed_end
            ):
                raise ValidationError(
                    _(
                        "Invalid Compensation Date: %(date)s.\n\n"
                        "The compensation date must be within "
                        "7 calendar days before or after the "
                        "Work From Home date (%(wfh_date)s)."
                    )
                    % {
                        "date": compensation_date,
                        "wfh_date": wfh_date,
                    }
                )

    @api.constrains(
        "date_from",
        "date_to",
        "compensation_date",
        "compensation_date_2",
        "compensation_date_3",
        "mode",
    )
    def _check_wfh_policy(self):
        self._validate_wfh_policy()


    def _get_allowed_compensation_dates(self, exception_date):
        """
        Return valid compensation dates.

        Rules:
            - Monday or Friday only.
            - Saturday and Sunday are automatically excluded.
            - Within 7 calendar days before or after exception date.
            - Exception date itself is never returned.
        """

        if not exception_date:
            return []

        valid_dates = []

        start_date = exception_date - timedelta(days=7)
        end_date = exception_date + timedelta(days=7)

        current_date = start_date

        while current_date <= end_date:

            # Monday = 0
            # Friday = 4
            if current_date.weekday() in (0, 4):

                if current_date != exception_date:
                    valid_dates.append(current_date)

            current_date += timedelta(days=1)

        return valid_dates

    # -------------------------------------------------------------------------
    # SUBMIT
    # -------------------------------------------------------------------------

    def action_submit(self):
        for record in self:

            if record.state != "draft":
                continue

            if not record.employee_id:
                raise UserError(
                    _("Employee is required.")
                )

            if not record.manager_id:
                raise UserError(
                    _(
                        "The employee does not have a manager "
                        "configured."
                    )
                )

            if not record.date_from or not record.date_to:
                raise UserError(
                    _("From Date and To Date are required.")
                )

            # ---------------------------------------------------------
            # Validate WFH / Exception Policy
            # ---------------------------------------------------------
            if record.is_regularization:
                record._validate_regularization_submit()
            else:
                record._validate_wfh_policy()
                record._check_monthly_home_exception()

            # ---------------------------------------------------------
            # Move to Manager Approval
            # ---------------------------------------------------------
            record.state = "manager_approval"

            # ---------------------------------------------------------
            # Manager Email
            # ---------------------------------------------------------
            manager_email = (
                record.manager_id.user_id.email
                if record.manager_id.user_id
                else False
            )

            # ---------------------------------------------------------
            # HR Support Email
            # ---------------------------------------------------------
            hr_email = "hrsupport@bxitech.com"

            # ---------------------------------------------------------
            # Prepare recipients
            # ---------------------------------------------------------
            recipients = [hr_email]

            if manager_email:
                recipients.append(manager_email.strip())

            # Remove duplicate / empty emails
            recipients = list(
                dict.fromkeys(
                    email for email in recipients if email
                )
            )

            email_to = ",".join(recipients)

            # ---------------------------------------------------------
            # Backend View Request URL
            # ---------------------------------------------------------
            view_request_url = record._get_view_request_url()

            # ---------------------------------------------------------
            # Mode Label
            # ---------------------------------------------------------
            mode_label = ""

            if record.mode:
                mode_label = dict(
                    record._fields["mode"].selection
                ).get(record.mode, "")

            # ---------------------------------------------------------
            # Email Subject
            # ---------------------------------------------------------
            subject = _(
                "Exception Working Request: %s"
            ) % record.name

            # ---------------------------------------------------------
            # Email Body
            # ---------------------------------------------------------
            if record.is_regularization:
                subject = _(
                    "%(category)s Request: %(name)s"
                ) % {
                    "category": record._get_category_label(),
                    "name": record.name,
                }
                body = record._get_regularization_submit_body(
                    view_request_url
                )
            else:
                body = record._get_exception_submit_body(
                    mode_label, view_request_url
                )

            # ---------------------------------------------------------
            # Send Email
            # ---------------------------------------------------------
            if email_to:
                try:
                    self.env["mail.mail"].sudo().create({
                        "subject": subject,
                        "body_html": body,
                        "email_from": "hrsupport@bxitech.com",
                        "email_to": email_to,
                        "auto_delete": True,
                    }).send()

                except Exception:
                    _logger.exception(
                        "Failed to send exception working "
                        "notification for %s",
                        record.name,
                    )

        return True

    def _get_view_request_url(self):
        self.ensure_one()
        base_url = self.env["ir.config_parameter"].sudo().get_param(
            "web.base.url"
        )
        return (
            f"{base_url}/web#"
            f"id={self.id}"
            f"&model=bxi.shift.exception"
            f"&view_type=form"
        )

    def _get_category_label(self):
        self.ensure_one()
        return dict(
            self._fields["category"]._description_selection(self.env)
        ).get(self.category, "")

    def _get_exception_submit_body(self, mode_label, view_request_url):
        self.ensure_one()
        record = self
        return _(
            "<p>Dear Manager / HR,</p>"

            "<p>"
            "Employee <strong>%s</strong> has submitted an "
            "Exception Working Request for your review."
            "</p>"

            "<p>"
            "<strong>From Date:</strong> %s<br/>"
            "<strong>To Date:</strong> %s<br/>"
            "<strong>Mode:</strong> %s<br/>"
            "<strong>Compensation Date(s):</strong> %s<br/>"
            "<strong>Reason:</strong> %s"
            "</p>"

            "<p>"
            "Please review the request and take the necessary action."
            "</p>"

            "<p style='margin-top:20px;'>"
            "<a href='%s' "
            "style='background-color:#875A7B;"
            "color:white;"
            "padding:10px 18px;"
            "text-decoration:none;"
            "border-radius:5px;"
            "display:inline-block;'>"
            "View Request"
            "</a>"
            "</p>"

            "<p>"
            "Regards,<br/>"
            "HR Support"
            "</p>"
        ) % (
            record.employee_id.name,
            record.date_from or "",
            record.date_to or "",
            mode_label,
            ", ".join(
                str(value) for value in record._get_compensation_dates()
            ),
            record.reason or "",
            view_request_url,
        )

    def _get_regularization_times_html(self):
        """Check-in/out lines of the times entered for the category."""
        self.ensure_one()
        lines = []
        if self.category == "attendance_regularization":
            lines.append(
                _("<strong>Check-in Time:</strong> %s<br/>")
                % self._float_to_time_str(self.regularize_check_in)
            )
        if self.category in ("attendance_regularization", "late_checkout"):
            lines.append(
                _("<strong>Check-out Time:</strong> %s<br/>")
                % self._float_to_time_str(self.regularize_check_out)
            )
        return "".join(lines)

    def _get_regularization_submit_body(self, view_request_url):
        self.ensure_one()
        return _(
            "<p>Dear Manager / HR,</p>"

            "<p>"
            "Employee <strong>%(employee)s</strong> has submitted a "
            "<strong>%(category)s</strong> request for your review."
            "</p>"

            "<p>"
            "<strong>Exception Date:</strong> %(date)s<br/>"
            "%(times)s"
            "<strong>Reason:</strong> %(reason)s"
            "</p>"

            "<p>"
            "Please review the request and take the necessary action."
            "</p>"

            "<p style='margin-top:20px;'>"
            "<a href='%(url)s' "
            "style='background-color:#875A7B;"
            "color:white;"
            "padding:10px 18px;"
            "text-decoration:none;"
            "border-radius:5px;"
            "display:inline-block;'>"
            "View Request"
            "</a>"
            "</p>"

            "<p>"
            "Regards,<br/>"
            "HR Support"
            "</p>"
        ) % {
            "employee": self.employee_id.name,
            "category": self._get_category_label(),
            "date": self.date_from or "",
            "times": self._get_regularization_times_html(),
            "reason": self.reason or "",
            "url": view_request_url,
        }

    # -------------------------------------------------------------------------
    # MANAGER APPROVAL
    # -------------------------------------------------------------------------

    def action_manager_approve(self):

        current_employee = self.env["hr.employee"].search(
            [
                ("user_id", "=", self.env.user.id),
            ],
            limit=1,
        )

        is_hr_manager = self.env.user.has_group(
            "hr.group_hr_manager"
        )

        for record in self:

            if record.state != "manager_approval":
                raise UserError(
                    _(
                        "Only requests in Manager Approval "
                        "state can be approved."
                    )
                )

            # Normal manager can approve only own team's request.
            # HR Manager can approve any request.
            if not is_hr_manager:

                if (
                    not current_employee
                    or record.manager_id.id
                    != current_employee.id
                ):
                    raise UserError(
                        _(
                            "You can approve only exception "
                            "requests submitted by your team members."
                        )
                    )

            if record.is_regularization:
                # Reporting Manager approved: HR gives the final approval,
                # the attendance is corrected only then.
                record._check_regularization_payroll()
                record.write(
                    {
                        "state": "hr_approval",
                        "manager_approved_by": (
                            current_employee.id
                            if current_employee
                            else False
                        ),
                        "manager_approved_date": fields.Datetime.now(),
                    }
                )
                record._send_hr_approval_mail()
                continue

            # Validate again before approval.
            record._validate_wfh_policy()
            record._snapshot_original_weekday_locations()

            # -------------------------------------------------------------
            # Do NOT change the employee weekly fields at approval time.
            #
            # The nightly cron is responsible for:
            #   - restoring today's field to its original location;
            #   - applying tomorrow's approved exception;
            #   - applying tomorrow's compensation-day location.
            #
            # This prevents a WFH request for 15-16 September from changing
            # Tuesday/Wednesday immediately on approval.
            # -------------------------------------------------------------

            # -------------------------------------------------------------
            # Change state after successful processing
            # -------------------------------------------------------------

            record.write(
                {
                    "state": "approved",
                    "manager_approved_by": (
                        current_employee.id
                        if current_employee
                        else False
                    ),
                    "manager_approved_date": fields.Datetime.now(),
                }
            )

            record._send_employee_decision_mail(_("Approved"), _("approved"))

        return True

    # -------------------------------------------------------------------------
    # HR APPROVAL (Attendance Regularization / Missing Timesheet / Late Checkout)
    # -------------------------------------------------------------------------

    def action_hr_approve(self):

        current_employee = self.env["hr.employee"].search(
            [
                ("user_id", "=", self.env.user.id),
            ],
            limit=1,
        )

        for record in self:

            if record.state != "hr_approval":
                raise UserError(
                    _(
                        "Only requests in HR Approval "
                        "state can be approved by HR."
                    )
                )

            if not record.can_hr_approve:
                raise UserError(
                    _("Only HR users can approve at this stage.")
                )

            record._check_regularization_payroll()
            record._apply_regularization()

            record.write(
                {
                    "state": "approved",
                    "hr_approved_by": (
                        current_employee.id
                        if current_employee
                        else False
                    ),
                    "hr_approved_date": fields.Datetime.now(),
                }
            )

            # Also after the cutoff: the LOP goes once all gaps are approved.
            record._cancel_lop_if_regularized()

            record._send_employee_decision_mail(_("Approved"), _("approved"))

        return True

    def _send_hr_approval_mail(self):
        """Tell HR that the Reporting Manager approved the request."""
        self.ensure_one()
        record = self
        subject = _(
            "%(category)s Request Awaiting HR Approval: %(name)s"
        ) % {
            "category": record._get_category_label(),
            "name": record.name,
        }
        body = _(
            "<p>Dear HR,</p>"

            "<p>"
            "The <strong>%(category)s</strong> request of "
            "<strong>%(employee)s</strong> has been approved by the "
            "reporting manager <strong>%(manager)s</strong> and is "
            "awaiting your approval."
            "</p>"

            "<p>"
            "<strong>Exception Date:</strong> %(date)s<br/>"
            "%(times)s"
            "<strong>Reason:</strong> %(reason)s"
            "</p>"

            "<p style='margin-top:20px;'>"
            "<a href='%(url)s' "
            "style='background-color:#875A7B;"
            "color:white;"
            "padding:10px 18px;"
            "text-decoration:none;"
            "border-radius:5px;"
            "display:inline-block;'>"
            "View Request"
            "</a>"
            "</p>"

            "<p>"
            "Regards,<br/>"
            "HR Support"
            "</p>"
        ) % {
            "category": record._get_category_label(),
            "employee": record.employee_id.name,
            "manager": self.env.user.name,
            "date": record.date_from or "",
            "times": record._get_regularization_times_html(),
            "reason": record.reason or "",
            "url": record._get_view_request_url(),
        }
        try:
            self.env["mail.mail"].sudo().create(
                {
                    "subject": subject,
                    "body_html": body,
                    "email_from": "hrsupport@bxitech.com",
                    "email_to": "hrsupport@bxitech.com",
                    "auto_delete": True,
                }
            ).send()
        except Exception:
            _logger.exception(
                "Failed to send HR approval email for %s",
                record.name,
            )

    def _send_employee_decision_mail(self, title, decision):
        self.ensure_one()
        record = self
        employee_email = (
            record.employee_id.user_id.email
            if record.employee_id.user_id
            else record.employee_id.work_email
        )

        if not employee_email:
            return

        try:
            subject, body = record._get_employee_decision_mail(title, decision)
            self.env["mail.mail"].sudo().create(
                {
                    "subject": subject,
                    "body_html": body,
                    "email_from": "hrsupport@bxitech.com",
                    "email_to": employee_email,
                    "auto_delete": True,
                }
            ).send()
        except Exception:
            _logger.exception(
                "Failed to send employee %s email for %s",
                decision,
                record.name,
            )

    def _get_employee_decision_mail(self, title, decision):
        """(subject, body) of the approval/refusal mail to the employee."""
        self.ensure_one()
        if self.is_regularization:
            subject = _("Your %(category)s Request %(title)s: %(name)s") % {
                "category": self._get_category_label(),
                "title": title,
                "name": self.name,
            }
            body = _(
                "<p>Your %(category)s request for "
                "<strong>%(date)s</strong> has been %(decision)s by "
                "<strong>%(user)s</strong>.</p>"
            ) % {
                "category": self._get_category_label().lower(),
                "date": self.date_from or "",
                "decision": decision,
                "user": self.env.user.name,
            }
            return subject, body

        subject = _("Your Exception Working Request %(title)s: %(name)s") % {
            "title": title,
            "name": self.name,
        }
        body = _(
            "<p>Your exception working request from "
            "<strong>%(date_from)s</strong> to <strong>%(date_to)s</strong> "
            "has been %(decision)s by "
            "<strong>%(user)s</strong>.</p>"
        ) % {
            "date_from": self.date_from or "",
            "date_to": self.date_to or "",
            "decision": decision,
            "user": self.env.user.name,
        }
        return subject, body

    def _snapshot_original_weekday_locations(self):
        """Save the employee's weekly locations before the first exception,
        so the daily cron can restore them after the exception days."""
        self.ensure_one()
        record = self

        # -------------------------------------------------------------
        # Weekday field mapping
        # -------------------------------------------------------------
        weekday_field_map = {
            0: "monday_location_id",
            1: "tuesday_location_id",
            2: "wednesday_location_id",
            3: "thursday_location_id",
            4: "friday_location_id",
            5: "saturday_location_id",
            6: "sunday_location_id",
        }

        emp = record.employee_id.sudo()

        # -------------------------------------------------------------
        # Capture the employee's ORIGINAL weekly locations.
        #
        # The cron uses this snapshot to restore the employee after the
        # exception day is finished.  If this employee already has an
        # exception with a saved snapshot, reuse that snapshot so a
        # second request does not accidentally save an already-modified
        # WFH location as the employee's "original" location.
        # -------------------------------------------------------------
        if not record.original_weekday_locations:
            orig = {}

            previous_exception = self.search(
                [
                    ("id", "!=", record.id),
                    ("employee_id", "=", emp.id),
                    ("original_weekday_locations", "!=", False),
                ],
                order="id asc",
                limit=1,
            )

            if previous_exception and previous_exception.original_weekday_locations:
                try:
                    orig = json.loads(
                        previous_exception.original_weekday_locations
                    )
                except (TypeError, ValueError):
                    _logger.warning(
                        "Invalid original_weekday_locations on %s",
                        previous_exception.name,
                    )

            if not orig:
                for weekday, field_name in weekday_field_map.items():
                    if field_name in emp._fields:
                        value = emp[field_name]
                        orig[field_name] = value.id if value else False

            record.original_weekday_locations = json.dumps(orig)

    # -------------------------------------------------------------------------
    # REFUSE
    # -------------------------------------------------------------------------
    def action_refuse(self):
        for record in self:

            if record.state not in (
                "manager_approval",
                "hr_approval",
                "draft",
            ):
                continue

            if record.state == "hr_approval" and not record.can_hr_approve:
                raise UserError(
                    _("Only HR users can refuse at this stage.")
                )

            # -------------------------------------------------------------
            # Change state to refused
            # -------------------------------------------------------------
            record.state = "refused"

            # After the cutoff the day is no longer regularized: LOP.
            if record.is_regularization:
                record._apply_regularization_lop_if_closed()

            record._send_employee_decision_mail(_("Refused"), _("refused"))

        return True

    # -------------------------------------------------------------------------
    # SET DRAFT
    # -------------------------------------------------------------------------

    def action_set_draft(self):
        for record in self:

            was_approved = record.state == "approved"

            record.state = "draft"

            record.manager_approved_by = False
            record.manager_approved_date = False
            record.hr_approved_by = False
            record.hr_approved_date = False

            if record.is_regularization:
                if was_approved:
                    record._revert_regularization()
                record._apply_regularization_lop_if_closed()

        return True

    # -------------------------------------------------------------------------
    # CRON - APPLY ACTIVE EXCEPTIONS / RESTORE EXPIRED LOCATIONS
    # -------------------------------------------------------------------------

    @api.model
    def cron_apply_and_cleanup_exceptions(self):
        """
        Nightly exception-working scheduler.

        Expected cron time: 23:00 every day.

        Example:
            WFH: 15-09-2026 to 16-09-2026
            Compensation: 14-09-2026 and 18-09-2026

        Night of 13 Sep:
            Monday (14 Sep) is prepared as the employee's original location.

        Night of 14 Sep:
            Monday is restored to original location.
            Tuesday (15 Sep) is changed to the WFH location.

        Night of 15 Sep:
            Tuesday is restored to original location.
            Wednesday (16 Sep) is changed to the WFH location.

        Night of 16 Sep:
            Wednesday is restored to original location.
            Thursday is prepared normally.

        Night of 17 Sep:
            Thursday is restored to original location.
            Friday (18 Sep) is set to the employee's original location
            because it is the compensation day.

        Therefore the employee's actual weekly location fields always represent
        the location that should be used for the next working day, while the
        original values are restored automatically after an exception day.
        """
        today = fields.Date.context_today(self)
        tomorrow = today + timedelta(days=1)

        _logger.info(
            "Starting BXI daily shift exception cron: today=%s, tomorrow=%s",
            today,
            tomorrow,
        )

        weekday_field_map = {
            0: "monday_location_id",
            1: "tuesday_location_id",
            2: "wednesday_location_id",
            3: "thursday_location_id",
            4: "friday_location_id",
            5: "saturday_location_id",
            6: "sunday_location_id",
        }

        # -------------------------------------------------------------
        # Find employees for whom an original weekly location snapshot
        # exists.  These are employees that have already had an exception
        # approved/processed.
        # -------------------------------------------------------------
        exception_records = self.search(
            [
                ("category", "=", "exception"),
                ("employee_id", "!=", False),
                ("original_weekday_locations", "!=", False),
            ]
        )

        employees = exception_records.mapped("employee_id").sudo()

        for employee in employees:
            baseline_exception = self.search(
                [
                    ("employee_id", "=", employee.id),
                    ("original_weekday_locations", "!=", False),
                ],
                order="id asc",
                limit=1,
            )

            if not baseline_exception:
                continue

            try:
                original_locations = json.loads(
                    baseline_exception.original_weekday_locations or "{}"
                )
            except (TypeError, ValueError):
                _logger.exception(
                    "Could not read original weekday locations for employee %s",
                    employee.name,
                )
                continue

            # ---------------------------------------------------------
            # 1. Restore ALL weekly fields to their original locations.
            #
            # This is the important part that makes the exception expire.
            # We do this before applying tomorrow's exception.
            # ---------------------------------------------------------
            restore_values = {}

            for weekday, field_name in weekday_field_map.items():
                if field_name not in employee._fields:
                    continue

                original_location_id = original_locations.get(field_name)

                if original_location_id:
                    restore_values[field_name] = int(original_location_id)
                else:
                    restore_values[field_name] = False

            if restore_values:
                employee.write(restore_values)

            # ---------------------------------------------------------
            # 2. Find an APPROVED exception that applies to TOMORROW.
            # ---------------------------------------------------------
            approved_requests = self.search(
                [
                    ("category", "=", "exception"),
                    ("employee_id", "=", employee.id),
                    ("state", "=", "approved"),
                ],
                order="id asc",
            )

            tomorrow_field_name = weekday_field_map.get(tomorrow.weekday())

            if not tomorrow_field_name or tomorrow_field_name not in employee._fields:
                continue

            tomorrow_location_id = False
            tomorrow_has_exception = False

            for exception in approved_requests:
                # -----------------------------------------------------
                # A. WFH / Home exception for tomorrow.
                # -----------------------------------------------------
                if (
                    exception.mode == "home"
                    and exception.date_from
                    and exception.date_to
                    and exception.date_from <= tomorrow <= exception.date_to
                    and tomorrow.weekday() in (1, 2, 3)
                ):
                    tomorrow_has_exception = True
                    tomorrow_location_id = (
                        exception.to_location_id.id
                        if exception.to_location_id
                        else False
                    )

                    _logger.info(
                        "Tomorrow %s is WFH for employee=%s "
                        "(request=%s, location=%s)",
                        tomorrow,
                        employee.name,
                        exception.name,
                        tomorrow_location_id,
                    )

                    # Home requests are restricted to one request per
                    # employee per calendar month, so normally there will
                    # not be another Home request competing here.
                    break

                # -----------------------------------------------------
                # B. Office / Client exception for tomorrow.
                #
                # Preserve the existing exception-working behaviour for
                # non-Home modes as well.
                # -----------------------------------------------------
                if (
                    exception.mode in ("office", "client")
                    and exception.date_from
                    and exception.date_to
                    and exception.date_from <= tomorrow <= exception.date_to
                ):
                    tomorrow_has_exception = True
                    tomorrow_location_id = (
                        exception.to_location_id.id
                        if exception.to_location_id
                        else False
                    )

                    _logger.info(
                        "Tomorrow %s is %s exception for employee=%s "
                        "(request=%s, location=%s)",
                        tomorrow,
                        exception.mode,
                        employee.name,
                        exception.name,
                        tomorrow_location_id,
                    )
                    break

                # -----------------------------------------------------
                # C. Compensation day.
                #
                # Compensation means the employee must work from the
                # ORIGINAL location configured for that weekday.
                # Because we restored all weekly fields above, using the
                # original snapshot here guarantees that WFH does not
                # remain on the compensation day.
                # -----------------------------------------------------
                if (
                    exception.mode == "home"
                    and tomorrow in exception._get_compensation_dates()
                ):
                    tomorrow_has_exception = True
                    tomorrow_location_id = original_locations.get(
                        tomorrow_field_name
                    )

                    if tomorrow_location_id:
                        tomorrow_location_id = int(tomorrow_location_id)

                    _logger.info(
                        "Tomorrow %s is compensation day for employee=%s "
                        "(request=%s, original location=%s)",
                        tomorrow,
                        employee.name,
                        exception.name,
                        tomorrow_location_id,
                    )
                    break

            # ---------------------------------------------------------
            # 3. Apply TOMORROW's exception to the actual employee
            #    weekday field.
            #
            # Example:
            #     tomorrow = Tuesday
            #     tomorrow_field_name = tuesday_location_id
            #     WFH location = Home
            #
            #     employee.tuesday_location_id = Home
            # ---------------------------------------------------------
            if tomorrow_has_exception:
                employee.write(
                    {
                        tomorrow_field_name: tomorrow_location_id,
                    }
                )

        _logger.info(
            "Completed BXI daily shift exception cron: today=%s, tomorrow=%s",
            today,
            tomorrow,
        )
        return True

    def _check_monthly_home_exception(self):
        """
        Allow only one Work From Home (Home mode) request
        per employee per calendar month.
        """
        for record in self:
            # Monthly restriction applies only to Home / WFH.
            if record.mode != "home" or record.is_regularization:
                continue
            if not record.employee_id:
                continue
            if not record.date_from:
                continue
            # Start and end of the month of the WFH request.
            month_start = record.date_from.replace(day=1)
            if month_start.month == 12:
                month_end = month_start.replace(
                    year=month_start.year + 1,
                    month=1,
                    day=1,
                ) - timedelta(days=1)
            else:
                month_end = month_start.replace(
                    month=month_start.month + 1,
                    day=1,
                ) - timedelta(days=1)

            # Find another active WFH request for the same employee
            # in the same calendar month.
            existing_request = self.search(
                [
                    ("id", "!=", record.id),
                    ("employee_id", "=", record.employee_id.id),
                    ("mode", "=", "home"),
                    ("date_from", ">=", month_start),
                    ("date_from", "<=", month_end),
                    ("state", "in", ("manager_approval", "approved")),
                ],
                limit=1,
            )

            if existing_request:
                raise ValidationError(
                    _(
                        "You have already raised a Work From Home request "
                        "for %(month)s %(year)s.\n\n"
                        "Existing Request: %(request)s\n"
                        "From Date: %(date_from)s\n"
                        "To Date: %(date_to)s\n\n"
                        "Only one Work From Home request is allowed "
                        "per calendar month."
                    )
                    % {
                        "month": record.date_from.strftime("%B"),
                        "year": record.date_from.year,
                        "request": existing_request.name,
                        "date_from": existing_request.date_from,
                        "date_to": existing_request.date_to,
                    }
                )