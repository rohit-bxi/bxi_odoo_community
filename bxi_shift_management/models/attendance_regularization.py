# -*- coding: utf-8 -*-

import logging
from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from odoo.addons.bxi_attendance_missed_checkout.models.hr_attendance import (
    REGULARIZATION_CUTOFF_DAY,
)


_logger = logging.getLogger(__name__)

# A working day can miss its attendance, its timesheet, or both. Each gap is
# cleared only by an approved request of its own categories.
GAP_ATTENDANCE = "attendance"
GAP_TIMESHEET = "timesheet"
GAP_CATEGORIES = {
    GAP_ATTENDANCE: ("attendance_regularization", "late_checkout"),
    GAP_TIMESHEET: ("missing_timesheet",),
}


class BxiShiftException(models.Model):
    """Attendance regularization: single-day requests that clear the gaps of
    a working day.

        - Attendance Regularization / Late Checkout: no check-in or check-out,
        - Missing Timesheet: no timesheet logged.

    A gap must be cleared by an approved request before the 25th cutoff of
    its attendance cycle (26th of the previous month to the 25th). A weekly
    cron sends the open gaps to the managers and HR, and at the cutoff a
    full-day LWP is applied to the days still having a gap. A late approval
    cancels that LWP until the payroll of the day is processed.
    """

    _inherit = "bxi.shift.exception"

    # -------------------------------------------------------------------------
    # ONCHANGE
    # -------------------------------------------------------------------------

    @api.onchange("category", "date_from", "employee_id")
    def _onchange_late_checkout_time(self):
        """Late Checkout: propose the check-out recorded on that day."""
        for record in self:
            if (
                record.category != "late_checkout"
                or not record.date_from
                or not record.employee_id
            ):
                continue
            attendance = record._get_late_checkout_attendance()
            # A missed check-out has no real check-out time to propose.
            if (
                not attendance
                or attendance.is_missed_checkout
                or not attendance.check_out
                or attendance.check_out <= attendance.check_in
            ):
                continue
            tz = record._get_employee_tz(record.employee_id)
            local_out = pytz.utc.localize(attendance.check_out).astimezone(tz)
            record.regularize_check_out = (
                local_out.hour + local_out.minute / 60.0 + local_out.second / 3600.0
            )

    # -------------------------------------------------------------------------
    # VALIDATION
    # -------------------------------------------------------------------------

    @api.constrains(
        "category",
        "date_from",
        "regularize_check_in",
        "regularize_check_out",
    )
    def _check_regularization_values(self):
        for record in self.filtered("is_regularization"):
            # Missing Timesheet has no times, Late Checkout only a check-out.
            if record.category == "attendance_regularization":
                if not (
                    0 <= record.regularize_check_in < 24
                    and 0 < record.regularize_check_out <= 24
                ):
                    raise ValidationError(
                        _("Check-in and Check-out Time must be between 00:00 and 24:00.")
                    )

                if record.regularize_check_out <= record.regularize_check_in:
                    raise ValidationError(
                        _("Check-out Time must be later than Check-in Time.")
                    )

            if (
                record.category == "late_checkout"
                and not 0 < record.regularize_check_out <= 24
            ):
                raise ValidationError(
                    _("Check-out Time must be between 00:00 and 24:00.")
                )

            if (
                record.date_from
                and record.date_from > fields.Date.context_today(record)
            ):
                raise ValidationError(
                    _("The Exception Date of a %(category)s request cannot be in the future.")
                    % {"category": record._get_category_label()}
                )

    def _validate_regularization_submit(self):
        self.ensure_one()
        Attendance = self.env["hr.attendance"].sudo()
        category = self._get_category_label()

        if not self.date_from:
            raise UserError(_("Exception Date is required."))

        # HR can still regularize a closed cycle, e.g. to correct an LOP.
        if not self.env.user.has_group("hr.group_hr_manager"):
            today = Attendance._get_regularization_today()
            open_start = Attendance._get_regularization_cycle(today)[0]
            if self.date_from < open_start:
                raise UserError(
                    _(
                        "The attendance cycle of %(date)s closed on %(cutoff)s.\n\n"
                        "A %(category)s request can no longer be submitted for "
                        "that day. Please contact HR."
                    )
                    % {
                        "date": self.date_from.strftime("%d-%m-%Y"),
                        "cutoff": (open_start - timedelta(days=1)).strftime("%d-%m-%Y"),
                        "category": category,
                    }
                )

        # Leaves are ignored: an LOP already applied can be regularized.
        working_dates = self._get_working_dates(
            self.employee_id, self.date_from, self.date_from, public_holidays_only=True
        )
        if self.date_from not in working_dates:
            raise UserError(
                _("%(date)s is not a working day of %(employee)s.")
                % {
                    "date": self.date_from.strftime("%d-%m-%Y"),
                    "employee": self.employee_id.name,
                }
            )

        if self.category == "late_checkout":
            attendance = self._get_late_checkout_attendance()
            if not attendance:
                raise UserError(
                    _(
                        "No check-in is recorded for %(employee)s on %(date)s.\n\n"
                        "Use the Attendance Regularization category to enter "
                        "both the check-in and the check-out time."
                    )
                    % {
                        "employee": self.employee_id.name,
                        "date": self.date_from.strftime("%d-%m-%Y"),
                    }
                )
            if self._get_regularization_datetimes()[3] <= attendance.check_in:
                raise UserError(
                    _("Check-out Time must be later than the recorded check-in (%(check_in)s).")
                    % {
                        "check_in": self._get_local_time_str(attendance.check_in),
                    }
                )

        if (
            self.category == "missing_timesheet"
            and self._get_timesheet_days(self.employee_id, self.date_from, self.date_from)
        ):
            raise UserError(
                _("A timesheet is already logged for %(employee)s on %(date)s.")
                % {
                    "employee": self.employee_id.name,
                    "date": self.date_from.strftime("%d-%m-%Y"),
                }
            )

        # One request per gap: attendance and timesheet are separate.
        duplicate = self.search(
            [
                ("id", "!=", self.id),
                ("employee_id", "=", self.employee_id.id),
                ("category", "in", GAP_CATEGORIES[self._get_gap_type()]),
                ("date_from", "=", self.date_from),
                ("state", "in", ("manager_approval", "hr_approval", "approved")),
            ],
            limit=1,
        )
        if duplicate:
            raise UserError(
                _(
                    "%(employee)s already has the request %(request)s for "
                    "%(date)s."
                )
                % {
                    "employee": self.employee_id.name,
                    "request": duplicate.name,
                    "date": self.date_from.strftime("%d-%m-%Y"),
                }
            )

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------

    def _get_gap_type(self):
        self.ensure_one()
        return (
            GAP_TIMESHEET
            if self.category in GAP_CATEGORIES[GAP_TIMESHEET]
            else GAP_ATTENDANCE
        )

    @api.model
    def _get_gap_labels(self):
        return {
            GAP_ATTENDANCE: _("Missing check-in / check-out"),
            GAP_TIMESHEET: _("Missing timesheet"),
        }

    @staticmethod
    def _float_to_time_str(value):
        """Format 9.5 as "09:30"."""
        minutes = round((value or 0.0) * 60)
        return "%02d:%02d" % (minutes // 60, minutes % 60)

    @api.model
    def _get_employee_tz(self, employee):
        """Same timezone as bxi_attendance uses for the attendance dates."""
        tz_name = (
            employee.tz
            or (employee.user_id and employee.user_id.tz)
            or self.env.user.tz
            or "Asia/Kolkata"
        )
        try:
            return pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            return pytz.timezone("Asia/Kolkata")

    def _get_local_time_str(self, utc_datetime):
        """"HH:MM" of a UTC datetime in the employee's timezone."""
        self.ensure_one()
        tz = self._get_employee_tz(self.employee_id)
        return pytz.utc.localize(utc_datetime).astimezone(tz).strftime("%H:%M")

    def _get_regularization_datetimes(self):
        """(local_in, local_out, utc_in, utc_out) of the regularized times;
        the utc values are naive, as stored on hr.attendance."""
        self.ensure_one()
        tz = self._get_employee_tz(self.employee_id)
        day_start = datetime.combine(self.date_from, time.min)
        local_in = tz.localize(day_start + timedelta(hours=self.regularize_check_in))
        local_out = tz.localize(day_start + timedelta(hours=self.regularize_check_out))
        return (
            local_in,
            local_out,
            local_in.astimezone(pytz.utc).replace(tzinfo=None),
            local_out.astimezone(pytz.utc).replace(tzinfo=None),
        )

    def _get_late_checkout_attendance(self):
        """Attendance whose check-out a Late Checkout corrects: the missed
        check-out of the day, else the last attendance of the day."""
        self.ensure_one()
        day_attendances = self._get_day_attendances(self.employee_id, self.date_from)
        missed = day_attendances.filtered(
            lambda att: att.is_missed_checkout or not att.check_out
        )
        return (missed or day_attendances)[-1:]

    @api.model
    def _get_day_attendances(self, employee, day):
        """Attendances of the employee checked in on the local day."""
        tz = self._get_employee_tz(employee)
        day_start = tz.localize(datetime.combine(day, time.min))
        day_end = day_start + timedelta(days=1)
        return self.env["hr.attendance"].sudo().search(
            [
                ("employee_id", "=", employee.id),
                ("check_in", ">=", day_start.astimezone(pytz.utc).replace(tzinfo=None)),
                ("check_in", "<", day_end.astimezone(pytz.utc).replace(tzinfo=None)),
            ],
            order="check_in",
        )

    @api.model
    def _get_working_dates(self, employee, date_from, date_to, public_holidays_only=False):
        """Days with working time in the employee's schedule. Public holidays
        are excluded; time off too unless public_holidays_only."""
        calendar = employee.resource_calendar_id
        if not calendar or date_from > date_to:
            return set()

        tz = self._get_employee_tz(employee)
        start = tz.localize(datetime.combine(date_from, time.min))
        end = tz.localize(datetime.combine(date_to, time.max))
        domain = (
            [("time_type", "=", "leave"), ("resource_id", "=", False)]
            if public_holidays_only
            else None
        )
        intervals = calendar.sudo()._work_intervals_batch(
            start, end, resources=employee.resource_id, domain=domain, tz=tz
        )[employee.resource_id.id]
        return {
            interval_start.astimezone(tz).date()
            for interval_start, _stop, _record in intervals
        }

    @api.model
    def _get_regularization_employees(self):
        return self.env["hr.employee"].sudo().search(
            [
                ("company_id.missed_checkout_lwp", "=", True),
                ("resource_calendar_id", "!=", False),
            ]
        )

    @api.model
    def _get_timesheet_days(self, employees, date_from, date_to):
        """{employee_id: {dates}} with a timesheet logged, in any state.
        Time off and public holiday lines are not timesheets."""
        AnalyticLine = self.env["account.analytic.line"].sudo()
        domain = [
            ("employee_id", "in", employees.ids),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
            ("unit_amount", ">", 0),
        ]
        for fname in ("holiday_id", "global_leave_id"):
            if fname in AnalyticLine._fields:
                domain.append((fname, "=", False))
        result = defaultdict(set)
        for line in AnalyticLine.search(domain):
            result[line.employee_id.id].add(line.date)
        return result

    @api.model
    def _get_regularization_gaps(
        self, employees, date_from, date_to, cleared_states=("approved",),
    ):
        """
        {employee_id: {date: {gaps}}} of the working days between date_from
        and date_to still having a gap:

            - attendance: no attendance, or a missed check-out,
            - timesheet: no timesheet logged (from the company's
              Check Timesheets From date),

        on office or home days (no client site, no deputation) without time
        off, and not cleared by a request of the gap in cleared_states.
        """
        result = {}
        if not employees or date_from > date_to:
            return result

        Attendance = self.env["hr.attendance"].sudo()
        employees = employees.sudo().filtered(
            lambda emp: emp.resource_calendar_id
            and emp.company_id.missed_checkout_lwp
            and Attendance._is_role_band_eligible_for_attendance(emp)
            and not ("is_on_deputation" in emp._fields and emp.is_on_deputation)
        )
        if not employees:
            return result

        complete_days = defaultdict(set)
        missed_days = defaultdict(set)
        attendances = Attendance.search(
            [
                ("employee_id", "in", employees.ids),
                ("check_in", ">=", datetime.combine(date_from - timedelta(days=1), time.min)),
                ("check_in", "<", datetime.combine(date_to + timedelta(days=2), time.min)),
            ]
        )
        for attendance in attendances:
            day = attendance._get_local_check_in_date()
            if attendance.is_missed_checkout or not attendance.check_out:
                missed_days[attendance.employee_id.id].add(day)
            else:
                complete_days[attendance.employee_id.id].add(day)

        timesheet_days = self._get_timesheet_days(employees, date_from, date_to)

        cleared = defaultdict(set)
        requests = self.sudo().search(
            [
                ("employee_id", "in", employees.ids),
                ("is_regularization", "=", True),
                ("state", "in", cleared_states),
                ("date_from", ">=", date_from),
                ("date_from", "<=", date_to),
            ]
        )
        for request in requests:
            cleared[(request.employee_id.id, request.date_from)].add(
                request._get_gap_type()
            )

        # The LOP of a gap is not a time off that clears the gap.
        leave_days = defaultdict(set)
        leaves = self.env["hr.leave"].sudo().search(
            [
                ("employee_id", "in", employees.ids),
                ("request_date_from", "<=", date_to),
                ("request_date_to", ">=", date_from),
                ("state", "not in", ("refuse", "cancel")),
                ("is_missed_checkout_lwp", "=", False),
            ]
        )
        for leave in leaves:
            day = max(leave.request_date_from, date_from)
            while day <= min(leave.request_date_to, date_to):
                leave_days[leave.employee_id.id].add(day)
                day += timedelta(days=1)

        for employee in employees:
            company = employee.company_id
            start = max(
                day for day in (
                    date_from,
                    company.missed_checkout_lwp_start_date,
                    company.attendance_regularization_start_date,
                    "emp_date_of_joining" in employee._fields
                    and employee.emp_date_of_joining,
                )
                if day
            )
            timesheet_start = company.timesheet_check_start_date

            # Time off is in leave_days, so that the LOP keeps its gaps.
            working_dates = self._get_working_dates(
                employee, start, date_to, public_holidays_only=True
            )
            days = {}
            for day in sorted(working_dates):
                if day in leave_days[employee.id]:
                    continue

                gaps = set()
                if (
                    day not in complete_days[employee.id]
                    or day in missed_days[employee.id]
                ):
                    gaps.add(GAP_ATTENDANCE)
                if (
                    timesheet_start
                    and day >= timesheet_start
                    and day not in timesheet_days[employee.id]
                ):
                    gaps.add(GAP_TIMESHEET)
                gaps -= cleared[(employee.id, day)]
                if not gaps:
                    continue

                # False for an approved client-site exception or no location.
                location = Attendance._get_effective_work_location(employee, day)
                if not location or not (location.office or location.home):
                    continue
                days[day] = gaps

            if days:
                result[employee.id] = days

        return result

    @api.model
    def _get_unregularized_days(
        self, employees, date_from, date_to, cleared_states=("approved",),
    ):
        """{employee_id: [dates]} of the days still having a gap."""
        return {
            employee_id: sorted(days)
            for employee_id, days in self._get_regularization_gaps(
                employees, date_from, date_to, cleared_states
            ).items()
        }

    # -------------------------------------------------------------------------
    # APPROVAL
    # -------------------------------------------------------------------------

    def _apply_regularization(self):
        """Correct the attendance of the day with the regularized times,
        count the hours within the shift and cancel the LOP of the day.

            - Attendance Regularization: check-in and check-out,
            - Late Checkout: check-out of the recorded attendance,
            - Missing Timesheet: attendance unchanged, DeskTime hours kept.
        """
        self.ensure_one()
        if self.category == "late_checkout":
            self._apply_late_checkout()
        elif self.category == "attendance_regularization":
            self._apply_attendance_regularization()

    def _check_regularization_payroll(self):
        """A late approval is allowed until the payroll of the day is done."""
        self.ensure_one()
        if "hr.payslip" not in self.env:
            return
        payslip = self.env["hr.payslip"].sudo().search(
            [
                ("employee_id", "=", self.employee_id.id),
                ("state", "=", "done"),
                ("date_from", "<=", self.date_from),
                ("date_to", ">=", self.date_from),
            ],
            limit=1,
        )
        if payslip:
            raise UserError(
                _(
                    "The payroll of %(employee)s for %(date)s is already processed "
                    "(%(payslip)s).\n\nThe %(category)s request can no longer be "
                    "approved."
                )
                % {
                    "employee": self.employee_id.name,
                    "date": self.date_from.strftime("%d-%m-%Y"),
                    "payslip": payslip.display_name,
                    "category": self._get_category_label(),
                }
            )

    def _cancel_lop_if_regularized(self):
        """Cancel the LOP of the day once all its gaps are approved."""
        self.ensure_one()
        if self._get_unregularized_days(
            self.employee_id, self.date_from, self.date_from
        ):
            return
        self._cancel_missed_attendance_lwp()

    def _apply_attendance_regularization(self):
        self.ensure_one()
        employee = self.employee_id.sudo()
        local_in, local_out, utc_in, utc_out = self._get_regularization_datetimes()

        day_attendances = self._get_day_attendances(employee, self.date_from)
        missed = day_attendances.filtered(
            lambda att: att.is_missed_checkout or not att.check_out
        )[-1:]

        # is_auto_checkout bypasses the GPS validation of bxi_attendance.
        values = {
            "check_out": utc_out,
            "is_auto_checkout": True,
            "regularization_id": self.id,
        }
        if missed:
            # Keep the check-in when other sessions of the day precede it.
            if not (day_attendances - missed):
                values["check_in"] = utc_in
            self._write_regularized_attendance(missed, values)
        elif not day_attendances:
            attendance = self.env["hr.attendance"].sudo().create(
                dict(values, employee_id=employee.id, check_in=utc_in)
            )
            self.write({"attendance_id": attendance.id, "attendance_created": True})
        # A complete attendance of the day is kept as it is.

        self.regularized_shift_hours = self._compute_regularized_shift_hours(
            local_in, local_out
        )

    def _apply_late_checkout(self):
        self.ensure_one()
        attendance = self._get_late_checkout_attendance()
        if not attendance:
            raise UserError(
                _("No check-in is recorded for %(employee)s on %(date)s.")
                % {
                    "employee": self.employee_id.name,
                    "date": self.date_from.strftime("%d-%m-%Y"),
                }
            )
        _local_in, local_out, _utc_in, utc_out = self._get_regularization_datetimes()
        self._write_regularized_attendance(
            attendance,
            {
                "check_out": utc_out,
                "is_auto_checkout": True,
                "regularization_id": self.id,
            },
        )

        # The day starts at the first check-in of the day.
        first_check_in = self._get_day_attendances(
            self.employee_id, self.date_from
        )[:1].check_in
        tz = self._get_employee_tz(self.employee_id)
        self.regularized_shift_hours = self._compute_regularized_shift_hours(
            pytz.utc.localize(first_check_in).astimezone(tz), local_out
        )

    def _write_regularized_attendance(self, attendance, values):
        """Write the regularized times, keeping the original ones to revert."""
        self.ensure_one()
        self.write(
            {
                "attendance_id": attendance.id,
                "attendance_created": False,
                "attendance_original_check_in": attendance.check_in,
                "attendance_original_check_out": attendance.check_out,
            }
        )
        attendance.write(values)

    def _compute_regularized_shift_hours(self, local_in, local_out):
        """Hours between local_in and local_out within the shift, lunch
        break included, as the DeskTime shift wise production hours."""
        self.ensure_one()
        intervals = self.env["bxi.desktime.log"].sudo().new(
            {"employee_id": self.employee_id.id, "date": self.date_from}
        )._get_shift_intervals()
        if not intervals:
            return round((local_out - local_in).total_seconds() / 3600.0, 4)

        start = max(local_in, intervals[0][0])
        stop = min(local_out, intervals[-1][1])
        if stop <= start:
            return 0.0
        seconds = sum(
            max((min(stop, interval_stop) - max(start, interval_start)).total_seconds(), 0)
            for interval_start, interval_stop, _attendances in intervals
        )
        return round(seconds / 3600.0, 4)

    def _cancel_missed_attendance_lwp(self):
        self.ensure_one()
        leaves = self.env["hr.leave"].sudo().search(
            [
                ("employee_id", "=", self.employee_id.id),
                ("is_missed_checkout_lwp", "=", True),
                ("request_date_from", "<=", self.date_from),
                ("request_date_to", ">=", self.date_from),
                ("state", "not in", ("refuse", "cancel")),
            ]
        )
        if not leaves:
            return
        leaves.with_context(
            mail_activity_automation_skip=True,
            tracking_disable=True,
        )._force_cancel(notify_responsibles=False)
        self.message_post(
            body=_("The LWP of %(date)s was cancelled: %(leaves)s")
            % {
                "date": self.date_from.strftime("%d-%m-%Y"),
                "leaves": ", ".join(leaves.mapped("display_name")),
            }
        )

    def _revert_regularization(self):
        """Undo the attendance correction of an approved regularization."""
        self.ensure_one()
        attendance = self.attendance_id.sudo()
        if attendance:
            if self.attendance_created:
                attendance.unlink()
            elif self.attendance_original_check_in:
                attendance.write(
                    {
                        "check_in": self.attendance_original_check_in,
                        "check_out": self.attendance_original_check_out,
                        "is_auto_checkout": True,
                        "regularization_id": False,
                    }
                )
        self.write(
            {
                "attendance_id": False,
                "attendance_created": False,
                "attendance_original_check_in": False,
                "attendance_original_check_out": False,
                "regularized_shift_hours": 0.0,
            }
        )

    # -------------------------------------------------------------------------
    # LOP
    # -------------------------------------------------------------------------

    @api.model
    def _apply_regularization_lop(self, employee, day):
        """Silent full-day LWP for a day not regularized before the cutoff."""
        Attendance = self.env["hr.attendance"].sudo()
        leave, _reason = Attendance._create_missed_checkout_lwp(employee, day)
        if leave:
            self._get_day_attendances(employee, day).filtered(
                "is_missed_checkout"
            ).write({"lwp_leave_id": leave.id})
        return leave

    def _apply_regularization_lop_if_closed(self):
        """A regularization withdrawn after the cutoff leaves the day LOP."""
        Attendance = self.env["hr.attendance"].sudo()
        today = Attendance._get_regularization_today()
        closed_end = Attendance._get_last_closed_regularization_cycle(today)[1]
        for record in self:
            if not record.date_from or record.date_from > closed_end:
                continue
            if self._get_unregularized_days(
                record.employee_id, record.date_from, record.date_from
            ):
                self._apply_regularization_lop(record.employee_id, record.date_from)

    # -------------------------------------------------------------------------
    # CRON
    # -------------------------------------------------------------------------

    @api.model
    def _get_regularization_summary_rows(self, employees, date_from, date_to):
        """Rows of the open gaps for the weekly summaries, one per gap."""
        gaps = self._get_regularization_gaps(employees, date_from, date_to)
        if not gaps:
            return []

        pending = {
            (request.employee_id.id, request.date_from, request._get_gap_type())
            for request in self.sudo().search(
                [
                    ("employee_id", "in", list(gaps)),
                    ("is_regularization", "=", True),
                    ("state", "in", ("manager_approval", "hr_approval")),
                    ("date_from", ">=", date_from),
                    ("date_from", "<=", date_to),
                ]
            )
        }
        labels = self._get_gap_labels()
        rows = []
        for employee in employees.filtered(lambda emp: emp.id in gaps).sorted("name"):
            for day, day_gaps in sorted(gaps[employee.id].items()):
                for gap in sorted(day_gaps):
                    rows.append({
                        "employee_id": employee.id,
                        "employee": employee.name,
                        "manager_id": employee.parent_id.id,
                        "company_id": employee.company_id.id,
                        "date": day.strftime("%d-%m-%Y (%a)"),
                        "issue": labels[gap],
                        "status": (
                            _("Awaiting approval")
                            if (employee.id, day, gap) in pending
                            else _("No request")
                        ),
                    })
        return rows

    @api.model
    def _cron_send_regularization_reminders(self):
        """Weekly, until the 25th: the open gaps of the cycle up to yesterday,
        one summary per manager (their team) and one to HR per company."""
        Attendance = self.env["hr.attendance"].sudo()
        today = Attendance._get_regularization_today()
        if today.day > REGULARIZATION_CUTOFF_DAY:
            return

        cycle_start, cycle_end = Attendance._get_regularization_cycle(today)
        date_to = min(today - timedelta(days=1), cycle_end)
        if date_to < cycle_start:
            return

        manager_template = self.env.ref(
            "bxi_shift_management.mail_template_regularization_manager_summary",
            raise_if_not_found=False,
        )
        hr_template = self.env.ref(
            "bxi_shift_management.mail_template_regularization_hr_summary",
            raise_if_not_found=False,
        )
        if not manager_template or not hr_template:
            _logger.error("Attendance regularization summary templates not found")
            return

        employees = self._get_regularization_employees()
        rows = self._get_regularization_summary_rows(employees, cycle_start, date_to)
        if not rows:
            return

        summary_context = {
            "regularization_period": "%s - %s" % (
                cycle_start.strftime("%d-%m-%Y"), date_to.strftime("%d-%m-%Y"),
            ),
            "regularization_deadline": cycle_end.strftime("%d-%m-%Y"),
        }

        rows_by_manager = defaultdict(list)
        rows_by_company = defaultdict(list)
        for row in rows:
            if row["manager_id"]:
                rows_by_manager[row["manager_id"]].append(row)
            rows_by_company[row["company_id"]].append(row)

        Employee = self.env["hr.employee"].sudo()
        for manager_id, manager_rows in rows_by_manager.items():
            manager = Employee.browse(manager_id)
            if not manager.work_email:
                _logger.warning(
                    "Attendance regularization summary not sent | manager=%s | no work email",
                    manager.name,
                )
                continue
            try:
                manager_template.sudo().with_context(
                    regularization_rows=manager_rows, **summary_context
                ).send_mail(manager.id, force_send=False)
            except Exception:
                _logger.exception(
                    "Attendance regularization summary failed | manager=%s", manager.name,
                )

        Company = self.env["res.company"].sudo()
        for company_id, company_rows in rows_by_company.items():
            try:
                hr_template.sudo().with_context(
                    regularization_rows=company_rows, **summary_context
                ).send_mail(company_id, force_send=False)
            except Exception:
                _logger.exception(
                    "Attendance regularization HR summary failed | company=%s",
                    Company.browse(company_id).name,
                )

    @api.model
    def _cron_apply_regularization_lop(self):
        """Monthly, after the 25th: LWP for the days of the closed cycle with
        a gap not approved, pending requests included. Neither the manager
        nor HR is notified."""
        Attendance = self.env["hr.attendance"].sudo()
        today = Attendance._get_regularization_today()
        cycle_start, cycle_end = Attendance._get_last_closed_regularization_cycle(today)

        employees = self._get_regularization_employees()
        unregularized = self._get_unregularized_days(employees, cycle_start, cycle_end)
        for employee in employees.filtered(lambda emp: emp.id in unregularized):
            for day in unregularized[employee.id]:
                try:
                    with self.env.cr.savepoint():
                        self._apply_regularization_lop(employee, day)
                except Exception:
                    _logger.exception(
                        "Attendance regularization LOP failed | employee=%s | date=%s",
                        employee.name, day,
                    )

    # -------------------------------------------------------------------------
    # DASHBOARD
    # -------------------------------------------------------------------------

    @api.model
    def _get_regularization_dashboard_overrides(self, employees, date_from, date_to):
        """{(employee_id, date): {'shift_prod': hours, 'status': status}}

            - day with a gap not approved: 0 hours, 'absent' ('lop' once the
              cutoff passed),
            - LWP for a day not regularized: 0 hours, 'lop',
            - approved attendance regularization: the regularized shift hours
              (an approved Missing Timesheet keeps the DeskTime hours).
        """
        result = {}
        if not employees:
            return result

        Attendance = self.env["hr.attendance"].sudo()
        today = Attendance._get_regularization_today()
        open_start = Attendance._get_regularization_cycle(today)[0]

        approved = self.sudo().search(
            [
                ("employee_id", "in", employees.ids),
                ("category", "in", GAP_CATEGORIES[GAP_ATTENDANCE]),
                ("state", "=", "approved"),
                ("date_from", ">=", date_from),
                ("date_from", "<=", date_to),
            ]
        )
        for request in approved:
            result[(request.employee_id.id, request.date_from)] = {
                "shift_prod": request.regularized_shift_hours,
                "status": False,
            }

        last_day = min(date_to, today - timedelta(days=1))
        for employee_id, days in self._get_unregularized_days(
            employees, date_from, last_day
        ).items():
            for day in days:
                result[(employee_id, day)] = {
                    "shift_prod": 0.0,
                    "status": "lop" if day < open_start else "absent",
                }

        lop_leaves = self.env["hr.leave"].sudo().search(
            [
                ("employee_id", "in", employees.ids),
                ("is_missed_checkout_lwp", "=", True),
                ("request_date_from", "<=", date_to),
                ("request_date_to", ">=", date_from),
                ("state", "not in", ("refuse", "cancel")),
            ]
        )
        for leave in lop_leaves:
            day = max(leave.request_date_from, date_from)
            while day <= min(leave.request_date_to, date_to):
                result[(leave.employee_id.id, day)] = {"shift_prod": 0.0, "status": "lop"}
                day += timedelta(days=1)

        return result


class ResCompany(models.Model):
    _inherit = "res.company"

    timesheet_check_start_date = fields.Date(
        string="Check Timesheets From",
        default=lambda self: self._default_timesheet_check_start_date(),
        help="From this date, a working day without timesheet is Absent until a "
             "Missing Timesheet request is approved, and LOP after the cutoff.",
    )

    def _default_timesheet_check_start_date(self):
        """Start of the next attendance cycle."""
        Attendance = self.env["hr.attendance"]
        cycle_end = Attendance._get_regularization_cycle(
            Attendance._get_regularization_today()
        )[1]
        return cycle_end + timedelta(days=1)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    timesheet_check_start_date = fields.Date(
        related="company_id.timesheet_check_start_date", readonly=False,
    )


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    regularization_id = fields.Many2one(
        "bxi.shift.exception",
        string="Regularization Request",
        readonly=True,
        copy=False,
        index="btree_not_null",
    )


class BxiTimesheetDashboard(models.AbstractModel):
    _inherit = "bxi.timesheet.dashboard"

    def _get_attendance_overrides(self, employees, start_date, end_date):
        result = super()._get_attendance_overrides(employees, start_date, end_date)
        result.update(
            self.env["bxi.shift.exception"]._get_regularization_dashboard_overrides(
                employees, start_date, end_date
            )
        )
        return result
