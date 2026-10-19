from odoo import models, fields, api
from datetime import date, datetime, time, timedelta
import calendar
import logging

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    emp_date_of_joining = fields.Date(string="Date Of Joining")

    # =========================================================
    # COMMON HELPERS
    # =========================================================

    @staticmethod
    def _get_quarter_dates(year, quarter):
        """Return start and end dates for a calendar quarter."""
        quarter_months = {
            1: (1, 3),
            2: (4, 6),
            3: (7, 9),
            4: (10, 12),
        }
        start_month, end_month = quarter_months[quarter]
        start_date = date(year, start_month, 1)
        end_date = date(
            year, end_month, calendar.monthrange(year, end_month)[1]
        )
        return start_date, end_date

    @staticmethod
    def _get_month_dates(year, month):
        """Return the first and last date of a month."""
        return (
            date(year, month, 1),
            date(year, month, calendar.monthrange(year, month)[1]),
        )

    @staticmethod
    def _get_working_days(start_date, end_date):
        """Count Monday-Friday dates (calendar holidays handled separately)."""
        if start_date > end_date:
            return 0
        count = 0
        current_date = start_date
        while current_date <= end_date:
            if current_date.weekday() < 5:
                count += 1
            current_date += timedelta(days=1)
        return count

    @staticmethod
    def _get_last_working_day(year, month):
        """Return the last Monday-Friday of a month."""
        last_day = date(year, month, calendar.monthrange(year, month)[1])
        while last_day.weekday() >= 5:
            last_day -= timedelta(days=1)
        return last_day

    def _get_period_datetimes(self, start_date, end_date):
        """Convert an inclusive date range to a half-open datetime range."""
        return (
            datetime.combine(start_date, time.min),
            datetime.combine(end_date + timedelta(days=1), time.min),
        )

    # =========================================================
    # ATTENDANCE HELPERS
    # =========================================================

    def _get_attendance_date_set(self, start_date, end_date):
        """Return unique dates with an attendance check-in."""
        self.ensure_one()
        start_dt, end_dt = self._get_period_datetimes(start_date, end_date)
        attendances = self.env['hr.attendance'].search([
            ('employee_id', '=', self.id),
            ('check_in', '>=', start_dt),
            ('check_in', '<', end_dt),
        ])
        return {
            attendance.check_in.date()
            for attendance in attendances
            if attendance.check_in
        }

    def _get_attendance_days(self, start_date, end_date):
        """Count unique attendance dates for compatibility with existing calls."""
        return len(self._get_attendance_date_set(start_date, end_date))

    # =========================================================
    # LEAVE HELPERS
    # =========================================================

    def _get_leave_type_by_code(self, code):
        """Find a leave type by the custom time_off_code field."""
        return self.env['hr.leave.type'].search([
            ('time_off_code', '=', code),
        ], limit=1)

    def _get_leave_days(self, leave_type, start_date, end_date):
        """Return approved leave duration for one leave type.

        Kept for compatibility with other code. The allocation methods below
        use unique dates instead, so attendance and leave cannot be double-counted.
        """
        self.ensure_one()
        if not leave_type or start_date > end_date:
            return 0.0

        leaves = self.env['hr.leave'].search([
            ('employee_id', '=', self.id),
            ('holiday_status_id', '=', leave_type.id),
            ('state', '=', 'validate'),
            ('request_date_from', '<=', end_date),
            ('request_date_to', '>=', start_date),
        ])
        total_days = 0.0
        for leave in leaves:
            leave_start = leave.request_date_from
            leave_end = leave.request_date_to
            if not leave_start or not leave_end:
                continue
            overlap_start = max(leave_start, start_date)
            overlap_end = min(leave_end, end_date)
            if overlap_start > overlap_end:
                continue
            if (
                leave_start >= start_date
                and leave_end <= end_date
                and getattr(leave, 'number_of_days', False)
            ):
                try:
                    total_days += float(leave.number_of_days)
                    continue
                except (TypeError, ValueError):
                    pass
            total_days += (overlap_end - overlap_start).days + 1
        return total_days

    def _get_public_holiday_date_set(self, start_date, end_date):
        """Return weekday public-holiday dates configured on resource calendars.

        This assumes public holidays are represented by resource.calendar.leaves
        with resource_id unset and calendar_id either unset (global) or matching
        the employee's resource calendar.
        """
        self.ensure_one()
        calendar_record = self.resource_calendar_id
        if not calendar_record or start_date > end_date:
            return set()

        start_dt, end_dt = self._get_period_datetimes(start_date, end_date)
        holidays = self.env['resource.calendar.leaves'].search([
            ('date_from', '<', end_dt),
            ('date_to', '>', start_dt),
            ('resource_id', '=', False),
            '|',
            ('calendar_id', '=', False),
            ('calendar_id', '=', calendar_record.id),
        ])

        holiday_dates = set()
        for holiday in holidays:
            if not holiday.date_from or not holiday.date_to:
                continue
            holiday_start = max(holiday.date_from.date(), start_date)
            holiday_end = min(holiday.date_to.date(), end_date)
            current_date = holiday_start
            while current_date <= holiday_end:
                if current_date.weekday() < 5:
                    holiday_dates.add(current_date)
                current_date += timedelta(days=1)
        return holiday_dates

    def _get_allocation_day_data(self, start_date, end_date):
        """Return (working_days, eligible_days) for RH/EL calculation.

        The denominator is every Monday-Friday date in the period. Public
        holidays do not reduce the denominator. The numerator counts unique
        weekdays with attendance, approved non-LWP leave, or a public holiday.
        LWP takes precedence and is excluded, including when it overlaps a
        public holiday or another leave record.
        """
        self.ensure_one()
        if start_date > end_date:
            return 0, 0

        # Count all Monday-Friday dates; do not subtract public holidays.
        weekday_dates = set()
        current_date = start_date
        while current_date <= end_date:
            if current_date.weekday() < 5:
                weekday_dates.add(current_date)
            current_date += timedelta(days=1)

        holiday_dates = (
            self._get_public_holiday_date_set(start_date, end_date)
            & weekday_dates
        )
        attendance_dates = (
            self._get_attendance_date_set(start_date, end_date)
            & weekday_dates
        )

        leaves = self.env['hr.leave'].search([
            ('employee_id', '=', self.id),
            ('state', '=', 'validate'),
            ('request_date_from', '<=', end_date),
            ('request_date_to', '>=', start_date),
        ])

        other_leave_dates = set()
        lwp_dates = set()
        for leave in leaves:
            leave_start = leave.request_date_from
            leave_end = leave.request_date_to
            if not leave_start or not leave_end:
                continue

            overlap_start = max(leave_start, start_date)
            overlap_end = min(leave_end, end_date)
            if overlap_start > overlap_end:
                continue

            leave_code = (
                getattr(leave.holiday_status_id, 'time_off_code', False) or ''
            ).strip().upper()
            leave_name = (leave.holiday_status_id.name or '').strip().upper()
            is_lwp = leave_code == 'LWP' or leave_name == 'LWP'

            current_date = overlap_start
            while current_date <= overlap_end:
                if current_date.weekday() < 5:
                    if is_lwp:
                        lwp_dates.add(current_date)
                    else:
                        other_leave_dates.add(current_date)
                current_date += timedelta(days=1)

        # A date covered by LWP is not eligible, even if another record
        # (including a public holiday) covers the same date.
        other_leave_dates -= lwp_dates

        # Set union ensures each eligible date is counted only once.
        eligible_dates = (
            attendance_dates
            | other_leave_dates
            | holiday_dates
        )
        eligible_dates -= lwp_dates
        eligible_dates &= weekday_dates

        return len(weekday_dates), len(eligible_dates)

    # =========================================================
    # RH MONTHLY ALLOCATION
    # =========================================================

    @api.model
    def cron_allocate_rh(self):
        """Allocate RH on day 1, using the previous month's data.

        Monthly rates within each calendar quarter are 0.33, 0.33 and 0.34.
        Formula: (monthly RH rate / working days) * eligible days.
        """
        today = fields.Date.context_today(self)
        if today.day != 1:
            _logger.info("RH cron skipped: today is not the first day of the month.")
            return

        previous_month_end = today - timedelta(days=1)
        month_start, month_end = self._get_month_dates(
            previous_month_end.year, previous_month_end.month
        )
        rh_type = self._get_leave_type_by_code('RH')
        if not rh_type:
            _logger.warning("RH leave type with time_off_code='RH' was not found.")
            return

        quarter = ((month_start.month - 1) // 3) + 1
        quarter_month = ((month_start.month - 1) % 3) + 1
        rh_rate = {1: 0.33, 2: 0.33, 3: 0.34}[quarter_month]
        month_key = month_start.strftime('%Y-%m')
        employees = self.search([
            ('active', '=', True),
            ('emp_date_of_joining', '!=', False),
        ])
        Allocation = self.env['hr.leave.allocation']

        for employee in employees:
            try:
                period_start = max(employee.emp_date_of_joining, month_start)
                if period_start > month_end:
                    continue

                working_days, eligible_days = employee._get_allocation_day_data(
                    period_start, month_end
                )
                if working_days <= 0 or eligible_days <= 0:
                    _logger.info(
                        "RH skipped for %s: working_days=%s, eligible_days=%s",
                        employee.name, working_days, eligible_days,
                    )
                    continue

                rh_days = round((rh_rate / float(working_days)) * eligible_days, 3)
                if rh_days <= 0:
                    continue

                allocation_name = f"RH Monthly {month_key}"
                existing = Allocation.search([
                    ('employee_id', '=', employee.id),
                    ('holiday_status_id', '=', rh_type.id),
                    ('name', '=', allocation_name),
                    ('state', '!=', 'refuse'),
                ], limit=1)
                if existing:
                    _logger.info(
                        "RH allocation already exists for %s: %s",
                        employee.name, allocation_name,
                    )
                    continue

                allocation = Allocation.create({
                    'name': allocation_name,
                    'employee_id': employee.id,
                    'holiday_status_id': rh_type.id,
                    'number_of_days': rh_days,
                })
                allocation.action_approve()

                _logger.info(
                    "RH allocated: employee=%s, month=%s, quarter=Q%s, "
                    "rate=%s, working_days=%s, eligible_days=%s, allocation=%s",
                    employee.name, month_key, quarter, rh_rate,
                    working_days, eligible_days, rh_days,
                )
            except Exception:
                _logger.exception(
                    "Failed to allocate RH for employee %s (%s).",
                    employee.name, employee.id,
                )

    # =========================================================
    # EL MONTHLY ALLOCATION
    # =========================================================

    @api.model
    def cron_allocate_el(self):
        """Allocate EL on day 1, using the previous month's data.

        Formula: (1.5 / working days) * eligible days.
        """
        today = fields.Date.context_today(self)
        if today.day != 1:
            _logger.info("EL cron skipped: today is not the first day of the month.")
            return

        previous_month_end = today - timedelta(days=1)
        month_start, month_end = self._get_month_dates(
            previous_month_end.year, previous_month_end.month
        )
        el_type = self._get_leave_type_by_code('EL')
        if not el_type:
            _logger.warning("EL leave type with time_off_code='EL' was not found.")
            return

        month_key = month_start.strftime('%Y-%m')
        employees = self.search([
            ('active', '=', True),
            ('emp_date_of_joining', '!=', False),
        ])
        Allocation = self.env['hr.leave.allocation']

        for employee in employees:
            try:
                period_start = max(employee.emp_date_of_joining, month_start)
                if period_start > month_end:
                    continue

                working_days, eligible_days = employee._get_allocation_day_data(
                    period_start, month_end
                )
                if working_days <= 0 or eligible_days <= 0:
                    _logger.info(
                        "EL skipped for %s: working_days=%s, eligible_days=%s",
                        employee.name, working_days, eligible_days,
                    )
                    continue

                el_days = round((1.5 / float(working_days)) * eligible_days, 3)
                if el_days <= 0:
                    continue

                allocation_name = f"EL Monthly {month_key}"
                existing = Allocation.search([
                    ('employee_id', '=', employee.id),
                    ('holiday_status_id', '=', el_type.id),
                    ('name', '=', allocation_name),
                    ('state', '!=', 'refuse'),
                ], limit=1)
                if existing:
                    _logger.info(
                        "EL allocation already exists for %s: %s",
                        employee.name, allocation_name,
                    )
                    continue

                allocation = Allocation.create({
                    'name': allocation_name,
                    'employee_id': employee.id,
                    'holiday_status_id': el_type.id,
                    'number_of_days': el_days,
                })
                allocation.action_approve()

                _logger.info(
                    "EL allocated: employee=%s, month=%s, working_days=%s, "
                    "eligible_days=%s, allocation=%s",
                    employee.name, month_key, working_days,
                    eligible_days, el_days,
                )
            except Exception:
                _logger.exception(
                    "Failed to allocate EL for employee %s (%s).",
                    employee.name, employee.id,
                )
