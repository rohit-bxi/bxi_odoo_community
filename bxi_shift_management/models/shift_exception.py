# -*- coding: utf-8 -*-

import json
import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


_logger = logging.getLogger(__name__)


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

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        tracking=True,
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

            current_date = record.date_from
            wfh_dates = []

            while current_date <= record.date_to:
                # Tuesday = 1
                # Wednesday = 2
                # Thursday = 3
                if current_date.weekday() in (1, 2, 3):
                    wfh_dates.append(current_date)

                current_date += timedelta(days=1)

            record.wfh_day_count = len(wfh_dates)

            record.show_compensation_date = (
                record.wfh_day_count >= 1
            )
            record.show_compensation_date_2 = (
                record.wfh_day_count >= 2
            )
            record.show_compensation_date_3 = (
                record.wfh_day_count >= 3
            )
            
    @api.onchange("mode", "date_from", "date_to")
    def _onchange_wfh_dates(self):
        for record in self:
            if record.mode != "home":
                record.compensation_date = False
                record.compensation_date_2 = False
                record.compensation_date_3 = False
                continue

            # Keep the compensation fields aligned with the number
            # of WFH days currently selected.
            wfh_day_count = record.wfh_day_count

            if wfh_day_count < 3:
                record.compensation_date_3 = False

            if wfh_day_count < 2:
                record.compensation_date_2 = False

            if wfh_day_count < 1:
                record.compensation_date = False

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("manager_approval", "Manager Approval"),
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

        records = super().create(vals_list)

        return records

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
        """Return all dates in the request period.
        Home/WFH is allowed only Tuesday, Wednesday and Thursday.
        """
        self.ensure_one()
        if not self.date_from or not self.date_to:
            return []

        dates = []
        current_date = self.date_from
        while current_date <= self.date_to:
            dates.append(current_date)
            current_date += timedelta(days=1)
        return dates

    def _get_compensation_dates(self):
        """Return the configured compensation dates in their field order."""
        self.ensure_one()
        return [
            value
            for value in (
                self.compensation_date,
                self.compensation_date_2,
                self.compensation_date_3,
            )
            if value
        ]

    def _validate_wfh_policy(self):
        """
        Validate the fixed WFH / exception working policy.

        Policy:
            - WFH is allowed only Tuesday, Wednesday and Thursday.
            - 1 WFH day requires 1 compensation day.
            - 2 WFH days require 2 compensation days.
            - 3 WFH days require 3 compensation days.
            - Compensation dates must be working days.
            - Under the current policy, compensation is Monday or Friday.
            - Each compensation date must be within +/- 7 calendar days
              of the WFH period.
            - Compensation dates must be unique and cannot be WFH dates.
        """
        for record in self:
            if record.mode != "home":
                continue

            if not record.date_from or not record.date_to:
                raise ValidationError(
                    _("From Date and To Date are required for Work From Home.")
                )

            wfh_dates = record._get_wfh_dates()

            # WFH is allowed only Tuesday / Wednesday / Thursday.
            invalid_wfh_dates = [
                value for value in wfh_dates if value.weekday() not in (1, 2, 3)
            ]
            if invalid_wfh_dates:
                raise ValidationError(
                    _(
                        "Work From Home is allowed only on Tuesday, "
                        "Wednesday or Thursday.\n\n"
                        "Invalid date: %(date)s"
                    )
                    % {"date": invalid_wfh_dates[0]}
                )

            wfh_day_count = len(wfh_dates)
            compensation_dates = record._get_compensation_dates()

            # Maximum supported by the existing fields.
            if wfh_day_count > 3:
                raise ValidationError(
                    _(
                        "A maximum of 3 Work From Home days is allowed "
                        "per request. Please raise another request for "
                        "additional WFH days."
                    )
                )

            # Exactly one compensation date per WFH day.
            if len(compensation_dates) != wfh_day_count:
                raise ValidationError(
                    _(
                        "Each Work From Home day requires exactly one "
                        "compensation day.\n\n"
                        "WFH Days: %(wfh_days)s\n"
                        "Compensation Dates Entered: %(comp_days)s"
                    )
                    % {
                        "wfh_days": wfh_day_count,
                        "comp_days": len(compensation_dates),
                    }
                )

            # No duplicate compensation dates.
            if len(compensation_dates) != len(set(compensation_dates)):
                raise ValidationError(
                    _("Compensation dates must be different.")
                )

            wfh_date_set = set(wfh_dates)
            for compensation_date in compensation_dates:
                # Current policy allows Monday or Friday only.
                if compensation_date.weekday() not in (0, 4):
                    raise ValidationError(
                        _(
                            "Invalid Compensation Date: %(date)s.\n\n"
                            "Compensation dates must be working days and, "
                            "under the current policy, can only be Monday "
                            "or Friday."
                        )
                        % {"date": compensation_date}
                    )

                # Compensation cannot be one of the WFH dates.
                if compensation_date in wfh_date_set:
                    raise ValidationError(
                        _(
                            "Compensation Date %(date)s cannot be one of "
                            "the Work From Home dates."
                        )
                        % {"date": compensation_date}
                    )

                # The compensation date must be within +/- 7 calendar
                # days of the complete WFH period.
                allowed_start = record.date_from - timedelta(days=7)
                allowed_end = record.date_to + timedelta(days=7)
                if not (allowed_start <= compensation_date <= allowed_end):
                    raise ValidationError(
                        _(
                            "Invalid Compensation Date: %(date)s.\n\n"
                            "Each compensation date must be within 7 "
                            "calendar days before or after the Work From "
                            "Home period (%(date_from)s to %(date_to)s)."
                        )
                        % {
                            "date": compensation_date,
                            "date_from": record.date_from,
                            "date_to": record.date_to,
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
            base_url = self.env["ir.config_parameter"].sudo().get_param(
                "web.base.url"
            )

            view_request_url = (
                f"{base_url}/web#"
                f"id={record.id}"
                f"&model=bxi.shift.exception"
                f"&view_type=form"
            )

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
            body = _(
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

            # Validate again before approval.
            record._validate_wfh_policy()

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

            # -------------------------------------------------------------
            # Notify employee
            # -------------------------------------------------------------

            employee_email = (
                record.employee_id.user_id.email
                if record.employee_id.user_id
                else record.employee_id.work_email
            )

            if employee_email:

                try:

                    subject = _(
                        "Your Exception Working Request Approved: %s"
                    ) % record.name

                    body = _(
                        "<p>Your exception working request from "
                        "<strong>%s</strong> to <strong>%s</strong> "
                        "has been approved by "
                        "<strong>%s</strong>.</p>"
                    ) % (
                        record.date_from or "",
                        record.date_to or "",
                        self.env.user.name,
                    )

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
                        "Failed to send employee approval "
                        "email for %s",
                        record.name,
                    )

        return True

    # -------------------------------------------------------------------------
    # REFUSE
    # -------------------------------------------------------------------------

    def action_refuse(self):
        for record in self:

            if record.state not in (
                "manager_approval",
                "draft",
            ):
                continue

            record.state = "refused"

        return True

    # -------------------------------------------------------------------------
    # SET DRAFT
    # -------------------------------------------------------------------------

    def action_set_draft(self):
        for record in self:

            record.state = "draft"

            record.manager_approved_by = False
            record.manager_approved_date = False

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
            if record.mode != "home":
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