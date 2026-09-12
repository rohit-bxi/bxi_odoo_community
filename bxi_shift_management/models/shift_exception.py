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

    mode = fields.Selection(
        [
            ("office", "Office"),
            ("home", "Home"),
            ("client", "Client Site"),
        ],
        string="Mode",
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
    @api.onchange("mode")
    def _onchange_mode(self):
        for record in self:
            if record.mode == "client":
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

    def _validate_wfh_policy(self):
        """
        Validate the fixed WFH / exception working policy.

        Policy:
            - WFH is allowed only Tuesday, Wednesday and Thursday.
            - Compensation date must be Monday or Friday.
            - Compensation date must be within +/- 7 calendar days.
            - Saturday and Sunday are automatically excluded.
        """

        for record in self:

            # This policy is applicable only for Home/WFH.
            if record.mode != "home":
                continue

            if not record.date_from or not record.date_to:
                raise ValidationError(
                    _(
                        "From Date and To Date are required "
                        "for Work From Home."
                    )
                )

            current_date = record.date_from

            while current_date <= record.date_to:

                # Tuesday = 1
                # Wednesday = 2
                # Thursday = 3
                if current_date.weekday() not in (1, 2, 3):
                    raise ValidationError(
                        _(
                            "Work From Home is allowed only on "
                            "Tuesday, Wednesday or Thursday.\n\n"
                            "Invalid date: %(date)s"
                        )
                        % {
                            "date": current_date,
                        }
                    )

                current_date += timedelta(days=1)

            # Compensation date is mandatory for Home/WFH.
            if not record.compensation_date:
                raise ValidationError(
                    _(
                        "Compensation Date is required for "
                        "Work From Home."
                    )
                )

            # For a single exception date, validate compensation date.
            #
            # Current business rule assumes one compensation date
            # for the exception request.
            if record.date_from == record.date_to:

                allowed_dates = (
                    record._get_allowed_compensation_dates(
                        record.date_from
                    )
                )

                if record.compensation_date not in allowed_dates:
                    formatted_dates = ", ".join(
                        str(value)
                        for value in allowed_dates
                    )

                    raise ValidationError(
                        _(
                            "Invalid Compensation Date.\n\n"
                            "For Work From Home on %(exception_date)s, "
                            "compensation can only be taken on Monday "
                            "or Friday within 7 calendar days before "
                            "or after the exception date.\n\n"
                            "Allowed compensation dates: %(dates)s"
                        )
                        % {
                            "exception_date": record.date_from,
                            "dates": formatted_dates or "None",
                        }
                    )

    @api.constrains(
        "date_from",
        "date_to",
        "compensation_date",
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

            # Validate WFH policy before submission.
            record._validate_wfh_policy()

            record.state = "manager_approval"

            manager_email = (
                record.manager_id.user_id.email
                if record.manager_id.user_id
                else False
            )

            if manager_email:
                try:
                    subject = _(
                        "Exception Working Request: %s"
                    ) % record.name

                    body = _(
                        "<p>Employee <strong>%s</strong> has requested "
                        "an exception working change from "
                        "<strong>%s</strong> to <strong>%s</strong>.</p>"
                        "<p><strong>Mode:</strong> %s</p>"
                        "<p><strong>Compensation Date:</strong> %s</p>"
                        "<p><strong>Reason:</strong> %s</p>"
                    ) % (
                        record.employee_id.name,
                        record.date_from or "",
                        record.date_to or "",
                        dict(
                            record._fields["mode"].selection
                        ).get(record.mode, "")
                        if record.mode
                        else "",
                        record.compensation_date or "",
                        record.reason or "",
                    )

                    self.env["mail.mail"].sudo().create(
                        {
                            "subject": subject,
                            "body_html": body,
                            "email_from": "hrsupport@bxitech.com",
                            "email_to": manager_email,
                            "auto_delete": True,
                        }
                    ).send()

                except Exception:
                    _logger.exception(
                        "Failed to send manager notification "
                        "for shift exception %s",
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

            EmployeeLocation = self.env[
                "bxi.shift.employee.location"
            ].sudo()

            orig = {}

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
            # Capture original employee weekday locations
            # -------------------------------------------------------------

            try:

                if not record.original_weekday_locations:

                    for idx, field_name in weekday_field_map.items():

                        if field_name in emp._fields:

                            orig[field_name] = (
                                emp[field_name].id
                                if emp[field_name]
                                else False
                            )

                    record.original_weekday_locations = json.dumps(
                        orig
                    )

            except Exception:
                _logger.exception(
                    "Failed to capture original weekday locations "
                    "for %s",
                    record.name,
                )

            # -------------------------------------------------------------
            # Apply exception location
            # -------------------------------------------------------------

            cur = record.date_from

            while cur <= record.date_to:

                weekday = cur.weekday()

                # Fixed policy:
                # Home/WFH -> Tuesday, Wednesday, Thursday only.
                #
                # Office/Hybrid can continue through the existing
                # location logic.

                if record.mode == "home":
                    if weekday not in (1, 2, 3):
                        cur += timedelta(days=1)
                        continue

                try:

                    EmployeeLocation.create(
                        {
                            "employee_id": emp.id,
                            "date": cur,
                            "location_id": (
                                record.to_location_id.id
                                if record.to_location_id
                                else False
                            ),
                            "exception_id": record.id,
                        }
                    )

                except Exception:
                    _logger.exception(
                        "Failed to create employee location "
                        "for exception %s on %s",
                        record.name,
                        cur,
                    )

                field_name = weekday_field_map.get(weekday)

                if (
                    field_name
                    and field_name in emp._fields
                    and record.to_location_id
                ):
                    try:

                        emp.write(
                            {
                                field_name:
                                    record.to_location_id.id
                            }
                        )

                    except Exception:
                        _logger.exception(
                            "Failed to update employee weekday "
                            "field %s for %s",
                            field_name,
                            emp.name,
                        )

                cur += timedelta(days=1)

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
        today = fields.Date.context_today(self)
        _logger.info(
            "Starting BXI daily shift exception cron for %s",
            today,
        )

        active_exceptions = self.search(
            [
                ("state", "=", "approved"),
                ("date_from", "<=", today),
                ("date_to", ">=", today),
            ]
        )

        weekday = today.weekday()

        weekday_fields = {
            0: "monday_location_id",
            1: "tuesday_location_id",
            2: "wednesday_location_id",
            3: "thursday_location_id",
            4: "friday_location_id",
            5: "saturday_location_id",
            6: "sunday_location_id",
        }

        field_name = weekday_fields.get(weekday)

        if not field_name:
            return True

        # -------------------------------------------------------------
        # 2. Apply today's exception location
        # -------------------------------------------------------------

        for exception in active_exceptions:

            employee = exception.employee_id.sudo()

            if not employee:
                continue

            # ---------------------------------------------------------
            # Fixed WFH rule:
            # Tuesday = 1
            # Wednesday = 2
            # Thursday = 3
            # ---------------------------------------------------------

            if exception.mode == "home":

                if weekday not in (1, 2, 3):
                    continue

            # Field must exist on employee.
            if field_name not in employee._fields:

                _logger.warning(
                    "Employee model does not contain %s",
                    field_name,
                )

                continue

            # ---------------------------------------------------------
            # Apply exception location
            # ---------------------------------------------------------

            if exception.to_location_id:

                employee.write(
                    {
                        field_name:
                            exception.to_location_id.id,
                    }
                )

                _logger.info(
                    "Applied exception %s: employee=%s, "
                    "date=%s, field=%s, location=%s",
                    exception.name,
                    employee.name,
                    today,
                    field_name,
                    exception.to_location_id.name,
                )

        # -------------------------------------------------------------
        # 3. Restore locations for expired exceptions
        # -------------------------------------------------------------

        expired_exceptions = self.search(
            [
                ("state", "=", "approved"),
                ("date_to", "<", today),
                ("original_weekday_locations", "!=", False),
            ]
        )

        for exception in expired_exceptions:

            employee = exception.employee_id.sudo()

            if not employee:
                continue

            try:

                original_locations = json.loads(
                    exception.original_weekday_locations
                    or "{}"
                )

            except Exception:

                _logger.exception(
                    "Invalid original weekday locations "
                    "for exception %s",
                    exception.name,
                )

                continue

            for field_name, location_id in (
                original_locations.items()
            ):

                if field_name not in employee._fields:
                    continue

                try:

                    employee.write(
                        {
                            field_name:
                                location_id or False,
                        }
                    )

                    _logger.info(
                        "Restored employee=%s field=%s "
                        "location=%s after exception %s expired",
                        employee.name,
                        field_name,
                        location_id,
                        exception.name,
                    )

                except Exception:

                    _logger.exception(
                        "Failed to restore employee=%s "
                        "field=%s for exception %s",
                        employee.name,
                        field_name,
                        exception.name,
                    )

            # Clear stored original values after restoration.
            exception.write(
                {
                    "original_weekday_locations": False,
                }
            )

        _logger.info(
            "Completed BXI daily shift exception cron for %s",
            today,
        )

        return True