# -*- coding: utf-8 -*-

import logging
import json
from datetime import timedelta, date

from odoo import api, fields, models, _
from odoo.exceptions import UserError


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

    allowed_weekdays = fields.Char(
        string="Allowed Weekdays",
        help="Comma-separated weekday numbers (0=Monday, 1=Tuesday, ..., 6=Sunday).",
    )

    mode = fields.Selection(
        [
            ("office", "Office"),
            ("home", "Home"),
            ("hybrid", "Hybrid"),
        ],
        string="Mode",
    )

    reason = fields.Text(
        string="Reason / Description",
    )

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

    # Store original weekday locations for the employee so we can restore them
    # after an exception ends. JSON mapping: {"monday_location_id": <id>, ...}
    original_weekday_locations = fields.Text(string='Original Weekday Locations', copy=False)
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
                    record.employee_id.company_id or self.env.company
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
                employee = self.env["hr.employee"].browse(employee_id).exists()
                if employee:
                    vals.setdefault("manager_id", employee.parent_id.id or False)
                    vals.setdefault(
                        "company_id",
                        employee.company_id.id or self.env.company.id,
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
                raise UserError(
                    _("To Date cannot be earlier than From Date.")
                )

    def action_submit(self):
        for record in self:

            if not record.employee_id:
                raise UserError(_("Employee is required."))

            if not record.manager_id:
                raise UserError(
                    _("The employee does not have a manager configured.")
                )

            if not record.date_from or not record.date_to:
                raise UserError(
                    _("From Date and To Date are required.")
                )

            if record.state != "draft":
                continue

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
                        "an exception working change from <strong>%s</strong> "
                        "to <strong>%s</strong>.</p>"
                        "<p><strong>Reason:</strong> %s</p>"
                    ) % (
                        record.employee_id.name,
                        record.date_from or "",
                        record.date_to or "",
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
                        "Failed to send manager notification for shift exception %s",
                        record.name,
                    )

        return True

    def action_manager_approve(self):
        current_employee = self.env["hr.employee"].search(
            [
                ("user_id", "=", self.env.user.id),
            ],
            limit=1,
        )
        for record in self:
            if record.state != "manager_approval":
                raise UserError(
                    _(
                        "Only requests in Manager Approval state "
                        "can be approved."
                    )
                )
            if (
                not current_employee
                or record.manager_id.id != current_employee.id
            ):
                raise UserError(
                    _(
                        "Only the employee's direct manager can approve "
                        "this request."
                    )
                )

            record.write(
                {
                    "state": "approved",
                    "manager_approved_by": current_employee.id,
                    "manager_approved_date": fields.Datetime.now(),
                }
            )

            # Apply per-date overrides and update the employee's weekday
            # location fields for the weekdays included in this exception.
            EmployeeLocation = self.env['bxi.shift.employee.location'].sudo()

            # Collect original weekday values to allow restore later.
            orig = {}
            weekday_field_map = {
                0: 'monday_location_id',
                1: 'tuesday_location_id',
                2: 'wednesday_location_id',
                3: 'thursday_location_id',
                4: 'friday_location_id',
                5: 'saturday_location_id',
                6: 'sunday_location_id',
            }

            emp = record.employee_id.sudo()

            # Save originals only once if not already stored
            try:
                if not record.original_weekday_locations:
                    for idx, field_name in weekday_field_map.items():
                        if field_name in emp._fields:
                            orig[field_name] = emp[field_name].id if emp[field_name] else False
                    record.original_weekday_locations = json.dumps(orig)
            except Exception:
                _logger.exception('Failed to capture original weekday locations for %s', record.name)

            # Iterate dates and create per-day override records
            cur = record.date_from
            while cur <= record.date_to:
                weekday = cur.weekday()

                # If allowed_weekdays is set, skip days not included
                if record.allowed_weekdays:
                    try:
                        allowed = [int(x.strip()) for x in record.allowed_weekdays.split(',') if x.strip()]
                    except Exception:
                        allowed = []
                    if allowed and weekday not in allowed:
                        cur = cur + timedelta(days=1)
                        continue

                # Create or update per-day override
                try:
                    EmployeeLocation.create({
                        'employee_id': emp.id,
                        'date': cur,
                        'location_id': record.to_location_id.id if record.to_location_id else False,
                        'exception_id': record.id,
                    })
                except Exception:
                    # If unique constraint prevents create, skip
                    pass

                # Update employee weekday field (set to to_location_id)
                field_name = weekday_field_map.get(weekday)
                if field_name and field_name in emp._fields and record.to_location_id:
                    try:
                        emp.write({field_name: record.to_location_id.id})
                    except Exception:
                        _logger.exception('Failed to update employee weekday field %s for %s', field_name, emp.name)

                cur = cur + timedelta(days=1)

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
                        "has been approved by <strong>%s</strong>.</p>"
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
                        "Failed to send employee approval email for %s",
                        record.name,
                    )

        return True

    def action_refuse(self):
        for record in self:
            if record.state not in ("manager_approval", "draft"):
                continue

            record.state = "refused"

        return True


    def action_set_draft(self):
        for record in self:
            record.state = "draft"

            record.manager_approved_by = False
            record.manager_approved_date = False

        return True

    @api.model
    def cron_apply_and_cleanup_exceptions(self):

        today = fields.Date.context_today(self)

        _logger.info(
            "Starting BXI daily shift exception cron for %s",
            today,
        )

        active_exceptions = self.search([
            ("state", "=", "approved"),
            ("date_from", "<=", today),
            ("date_to", ">=", today),
        ])

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

        for exception in active_exceptions:
            employee = exception.employee_id.sudo()

            if not employee:
                continue

            # Check whether today's weekday is included
            if exception.allowed_weekdays:

                try:
                    allowed_weekdays = [
                        int(value.strip())
                        for value in exception.allowed_weekdays.split(",")
                        if value.strip()
                    ]
                except (TypeError, ValueError):

                    _logger.warning(
                        "Invalid allowed_weekdays '%s' "
                        "for exception %s",
                        exception.allowed_weekdays,
                        exception.name,
                    )

                    continue

                if weekday not in allowed_weekdays:
                    continue

            # Field must exist on employee
            if field_name not in employee._fields:
                _logger.warning(
                    "Employee model does not contain %s",
                    field_name,
                )
                continue

            # -----------------------------------------------------
            # Apply exception location
            # -----------------------------------------------------

            if exception.to_location_id:

                employee.write({
                    field_name: exception.to_location_id.id,
                })

                _logger.info(
                    "Applied exception %s: employee=%s, "
                    "date=%s, field=%s, location=%s",
                    exception.name,
                    employee.name,
                    today,
                    field_name,
                    exception.to_location_id.name,
                )

        # ---------------------------------------------------------
        # 3. Restore locations for expired exceptions
        # ---------------------------------------------------------

        expired_exceptions = self.search([
            ("state", "=", "approved"),
            ("date_to", "<", today),
            ("original_weekday_locations", "!=", False),
        ])

        for exception in expired_exceptions:

            employee = exception.employee_id.sudo()

            if not employee:
                continue

            try:
                original_locations = json.loads(
                    exception.original_weekday_locations or "{}"
                )
            except Exception:

                _logger.exception(
                    "Invalid original weekday locations "
                    "for exception %s",
                    exception.name,
                )

                continue

            for field_name, location_id in original_locations.items():

                if field_name not in employee._fields:
                    continue

                employee.write({
                    field_name: location_id or False,
                })

                _logger.info(
                    "Restored employee=%s field=%s location=%s "
                    "after exception %s expired",
                    employee.name,
                    field_name,
                    location_id,
                    exception.name,
                )

            exception.write({
                "original_weekday_locations": False,
            })

        _logger.info(
            "Completed BXI daily shift exception cron for %s",
            today,
        )

        return True