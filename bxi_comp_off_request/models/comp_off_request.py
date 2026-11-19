from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, time, timedelta
import pytz


ACTIVE_STATES = (
    "submitted",
    "manager_approved",
    "hr_approved",
    "worked",
    "credited",
)


class HrCompOffRequest(models.Model):
    _name = "hr.comp.off.request"
    _description = "Comp-Off Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "work_date desc, id desc"

    name = fields.Char(
        string="Request Reference",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
        tracking=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,
        default=lambda self: self.env.user.employee_id,
        index=True,
        tracking=True,
    )
    department_id = fields.Many2one(
        related="employee_id.department_id",
        string="Department",
        store=True,
        readonly=True,
    )
    manager_id = fields.Many2one(
        "hr.employee",
        string="Reporting Manager",
        related="employee_id.parent_id",
        store=True,
        readonly=True,
    )
    work_date = fields.Date(
        string="Weekend Work Date",
        required=True,
        tracking=True,
        help="The Saturday or Sunday the employee plans to work.",
    )
    comp_off_date = fields.Date(
        string="Comp-Off Date",
        required=True,
        tracking=True,
        help="The weekday (Monday to Friday) the employee plans to take off.",
    )
    attendance_hours = fields.Float(
        string="Verified Attendance Hours",
        readonly=True,
        copy=False,
        tracking=True,
    )
    allocation_id = fields.Many2one(
        "hr.leave.allocation",
        string="Comp-Off Allocation",
        readonly=True,
        copy=False,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Waiting for Manager"),
            ("manager_approved", "Waiting for HR"),
            ("hr_approved", "Approved - Awaiting Weekend Work"),
            ("worked", "Attendance Verified"),
            ("credited", "Comp-Off Credited"),
            ("refused", "Refused"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
        copy=False,
        index=True,
    )
    comp_off_days = fields.Float(
        string="Comp-Off Days",
        readonly=True,
        copy=False,
        tracking=True,
    )
    attendance_id = fields.Many2one(
        "hr.attendance",
        string="Comp-Off Attendance",
        readonly=True,
        copy=False,
    )
    manager_approved_by = fields.Many2one("res.users", readonly=True, copy=False)
    manager_approved_on = fields.Datetime(readonly=True, copy=False)
    hr_approved_by = fields.Many2one("res.users", readonly=True, copy=False)
    hr_approved_on = fields.Datetime(readonly=True, copy=False)
    attendance_verified_by = fields.Many2one("res.users", readonly=True, copy=False)
    attendance_verified_on = fields.Datetime(readonly=True, copy=False)
    notes = fields.Text(string="Employee Notes")
    refusal_reason = fields.Text(string="Refusal Reason", tracking=True)

    _sql_constraints = [
        (
            "comp_off_employee_work_date_unique",
            "unique(employee_id, work_date)",
            "An employee can create only one Comp-Off request for a weekend work date.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "hr.comp.off.request"
                ) or _("New")
        records = super().create(vals_list)
        return records

    @api.constrains("employee_id", "work_date", "comp_off_date")
    def _check_request_dates(self):
        for rec in self:
            if rec.work_date and rec.work_date.weekday() not in (5, 6):
                raise ValidationError(
                    _("Weekend Work Date must be a Saturday or Sunday.")
                )

            if rec.comp_off_date and rec.comp_off_date.weekday() >= 5:
                raise ValidationError(
                    _("Comp-Off Date must be Monday through Friday.")
                )

            if rec.work_date and rec.comp_off_date:
                if (
                    rec.work_date.year != rec.comp_off_date.year
                    or rec.work_date.month != rec.comp_off_date.month
                ):
                    raise ValidationError(
                        _("Weekend Work Date and Comp-Off Date must be in the same month.")
                    )
                
    def _check_submission_month(self):
        today = fields.Date.context_today(self)

        for rec in self:
            if not rec.work_date or not rec.comp_off_date:
                continue

            if (
                today.year != rec.work_date.year
                or today.month != rec.work_date.month
            ):
                raise ValidationError(
                    _(
                        "You must submit the Comp-Off request in the same "
                        "calendar month as the weekend work date."
                    )
                )
                    
    def _check_employee_role_band(self):
        for rec in self:
            role_band = rec.employee_id.role_band

            if not role_band:
                raise ValidationError(
                    _("Employee Role Band is not configured.")
                )

            try:
                band_value = float(role_band.strip())
            except (ValueError, AttributeError):
                raise ValidationError(
                    _("Employee Role Band must contain a numeric value.")
                )

            if not 0.0 <= band_value <= 3.9:
                raise ValidationError(
                    _(
                        "Comp-Off is available only for employees whose "
                        "Role Band is between 0 and 3.9. "
                        "Current employee band: %s"
                    ) % role_band
                )

    def _check_employee_access(self):
        if self.env.su or self.env.user.has_group("hr_holidays.group_hr_holidays_manager"):
            return
        current_employee = self.env.user.employee_id
        for rec in self:
            is_manager = (
                rec.employee_id.parent_id
                and rec.employee_id.parent_id.user_id == self.env.user
            )
            if rec.employee_id != current_employee and not is_manager:
                raise UserError(_("You can only process your own requests or requests assigned to you as manager."))

    def _get_comp_off_leave_type(self):
        LeaveType = self.env["hr.leave.type"].sudo()
        candidates = LeaveType.search(
            [
                "|", "|",
                ("name", "ilike", "Comp-Off"),
                ("name", "ilike", "Comp Off"),
                ("name", "ilike", "Compoff"),
            ]
        )
        for leave_type in candidates:
            code = (
                getattr(leave_type, "time_off_code", False)
                or getattr(leave_type, "leave_code", False)
                or getattr(leave_type, "code", False)
                or ""
            ).strip().upper().replace("_", "-")
            normalized_name = (leave_type.name or "").strip().upper().replace("_", "-")
            if code in ("COMP-OFF", "COMPOFF") or normalized_name in (
                "COMP-OFF", "COMP OFF", "COMPOFF"
            ):
                return leave_type
        raise UserError(
            _(
                "Could not find the existing Comp-Off Time Off Type. "
                "Configure a leave type named Comp-Off (or Comp Off/Compoff), "
                "or set its code to COMP-OFF."
            )
        )
    def _get_completed_attendance_hours(self):
        self.ensure_one()

        if not self.employee_id or not self.work_date:
            return 0.0

        start_dt = fields.Datetime.to_datetime(self.work_date)
        end_dt = start_dt + timedelta(days=1)

        attendances = self.env["hr.attendance"].sudo().search([
            ("employee_id", "=", self.employee_id.id),
            ("check_in", ">=", fields.Datetime.to_string(start_dt)),
            ("check_in", "<", fields.Datetime.to_string(end_dt)),
            ("check_out", "!=", False),
        ])

        return sum(attendances.mapped("worked_hours"))

    
    def _create_comp_off_attendance(self):
        self.ensure_one()

        if self.attendance_id:
            raise UserError(
                _("Attendance has already been created for this Comp-Off request.")
            )

        total_hours = self._get_completed_attendance_hours()

        if total_hours <= 0:
            raise UserError(
                _("No completed attendance was found for the selected work date.")
            )

        # Calculate the Comp-Off credit.
        comp_off_days = 1.0 if total_hours >= 7.0 else 0.5

        # One day = 8 attendance hours; half day = 4 attendance hours.
        credited_hours = 8.0 * comp_off_days

        # Use the employee's working calendar timezone.
        timezone_name = (
            self.employee_id.resource_calendar_id.tz
            or self.env.user.tz
            or "UTC"
        )
        employee_tz = pytz.timezone(timezone_name)

        # Attendance starts at 9:00 AM on the Comp-Off date.
        local_start = employee_tz.localize(
            datetime.combine(self.comp_off_date, time(9, 0))
        )
        local_end = local_start + timedelta(hours=credited_hours)

        # Odoo stores Datetime values in UTC.
        check_in = local_start.astimezone(pytz.UTC).replace(tzinfo=None)
        check_out = local_end.astimezone(pytz.UTC).replace(tzinfo=None)

        # Prevent duplicate attendance on the Comp-Off date.
        day_start = employee_tz.localize(
            datetime.combine(self.comp_off_date, time.min)
        ).astimezone(pytz.UTC).replace(tzinfo=None)

        day_end = employee_tz.localize(
            datetime.combine(
                self.comp_off_date + timedelta(days=1), time.min
            )
        ).astimezone(pytz.UTC).replace(tzinfo=None)

        existing_attendance = self.env["hr.attendance"].sudo().search([
            ("employee_id", "=", self.employee_id.id),
            ("check_in", "<", day_end),
            "|",
            ("check_out", "=", False),
            ("check_out", ">", day_start),
        ], limit=1)

        if existing_attendance:
            raise UserError(
                _(
                    "An attendance record already exists for this employee "
                    "on the Comp-Off date (%s). Please check it before proceeding."
                ) % self.comp_off_date
            )

        attendance = self.env["hr.attendance"].sudo().with_context(
            is_comp_off_attendance=True
        ).create({
            "employee_id": self.employee_id.id,
            "check_in": fields.Datetime.to_string(check_in),
            "check_out": fields.Datetime.to_string(check_out),
        })

        self.write({
            "attendance_hours": total_hours,
            "comp_off_days": comp_off_days,
            "attendance_id": attendance.id,
            "attendance_verified_by": self.env.user.id,
            "attendance_verified_on": fields.Datetime.now(),
            "state": "credited",
        })

        self.message_post(
            body=_(
                "Weekend attendance verified: %.2f hours. "
                "Comp-Off credited: %.1f day(s). "
                "Attendance created on %s for %.2f hours."
            ) % (
                total_hours,
                comp_off_days,
                self.comp_off_date,
                credited_hours,
            )
        )

        return True


    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only draft requests can be submitted."))
            rec._check_employee_access()
            rec._check_request_dates()
            rec._check_submission_month()
            rec._check_employee_role_band()
            if not rec.employee_id.parent_id:
                raise UserError(
                    _("Please set a Reporting Manager on the employee record before submitting.")
                )
            rec.write({"state": "submitted"})
            rec.message_post(
                body=_("Comp-Off request submitted for Reporting Manager approval.")
            )
        return True

    def action_manager_approve(self):
        for rec in self:
            if rec.state != "submitted":
                raise UserError(_("Only requests waiting for the manager can be approved."))
            if not (
                self.env.user.has_group("hr_holidays.group_hr_holidays_manager")
                or (rec.employee_id.parent_id and rec.employee_id.parent_id.user_id == self.env.user)
            ):
                raise UserError(_("Only the employee's Reporting Manager can approve this request."))
            rec.write({
                "state": "manager_approved",
                "manager_approved_by": self.env.user.id,
                "manager_approved_on": fields.Datetime.now(),
            })
            rec.message_post(body=_("Approved by Reporting Manager. Sent to HR for approval."))

    def action_hr_approve(self):
        if not self.env.user.has_group("hr_holidays.group_hr_holidays_manager"):
            raise UserError(_("Only an HR Time Off Manager can provide the second approval."))
        for rec in self:
            if rec.state != "manager_approved":
                raise UserError(_("Only manager-approved requests can be approved by HR."))
            rec._check_request_dates()
            rec.write({
                "state": "hr_approved",
                "hr_approved_by": self.env.user.id,
                "hr_approved_on": fields.Datetime.now(),
            })
            rec.message_post(
                body=_("Approved by HR. After the weekend work is completed, verify attendance to credit Comp-Off.")
            )

    def action_verify_attendance_and_credit(self):
        self.ensure_one()

        if not self.env.user.has_group(
            "hr_holidays.group_hr_holidays_manager"
        ):
            raise UserError(
                _("Only an HR Time Off Manager can verify weekend attendance.")
            )

        if self.state not in ("hr_approved", "worked"):
            raise UserError(
                _("Only HR-approved requests can be verified.")
            )

        if self.work_date >= fields.Date.context_today(self):
            raise UserError(
                _("Weekend attendance can only be verified after the work date.")
            )

        self._check_employee_role_band()

        if self.attendance_id:
            raise UserError(
                _("Attendance has already been created for this request.")
            )

        total_hours = self._get_completed_attendance_hours()

        if total_hours <= 0:
            raise UserError(
                _("No completed attendance was found for the selected work date.")
            )

        self._create_comp_off_attendance()

        if total_hours < 7.0:
            message = _(
                "Attendance is %.2f hours. Half-day Comp-Off (0.5 day) "
                "has been credited because attendance is below 7 hours."
            ) % total_hours
        else:
            message = _(
                "Attendance is %.2f hours. Full-day Comp-Off (1 day) "
                "has been credited."
            ) % total_hours

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Comp-Off Attendance Verification"),
                "message": message,
                "type": "warning" if total_hours < 7.0 else "success",
                "sticky": True,
            },
        }

    def action_refuse(self):
        for rec in self:
            if rec.state not in ("submitted", "manager_approved", "hr_approved"):
                raise UserError(_("Only pending requests can be refused."))
            if rec.state == "submitted":
                allowed = (
                    self.env.user.has_group("hr_holidays.group_hr_holidays_manager")
                    or (rec.employee_id.parent_id and rec.employee_id.parent_id.user_id == self.env.user)
                )
                if not allowed:
                    raise UserError(_("Only the Reporting Manager can refuse this request at this stage."))
            elif not self.env.user.has_group("hr_holidays.group_hr_holidays_manager"):
                raise UserError(_("Only an HR Time Off Manager can refuse at this stage."))
            rec.write({"state": "refused"})
            rec.message_post(body=_("Comp-Off request refused."))

    def action_cancel(self):
        for rec in self:
            if rec.state not in ("draft", "submitted", "manager_approved", "hr_approved"):
                raise UserError(_("A credited or completed Comp-Off request cannot be cancelled here."))
            if rec.employee_id != self.env.user.employee_id and not self.env.user.has_group(
                "hr_holidays.group_hr_holidays_manager"
            ):
                raise UserError(_("You can only cancel your own request."))
            rec.write({"state": "cancelled"})
            rec.message_post(body=_("Comp-Off request cancelled."))

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ("refused", "cancelled"):
                raise UserError(_("Only refused or cancelled requests can be reset to draft."))
            if rec.employee_id != self.env.user.employee_id and not self.env.user.has_group(
                "hr_holidays.group_hr_holidays_manager"
            ):
                raise UserError(_("You can only reset your own request."))
            rec.write({
                "state": "draft",
                "refusal_reason": False,
                "manager_approved_by": False,
                "manager_approved_on": False,
                "hr_approved_by": False,
                "hr_approved_on": False,
                "attendance_hours": 0.0,
                "attendance_verified_by": False,
                "attendance_verified_on": False,
            })
