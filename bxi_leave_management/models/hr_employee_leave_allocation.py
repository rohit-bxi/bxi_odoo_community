from odoo import models, fields, api, _
from datetime import date, datetime, timedelta
import calendar
import logging

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    emp_date_of_joining = fields.Date(
        string="Date Of Joining"
    )

    # =========================================================
    # COMMON HELPERS
    # =========================================================

    @staticmethod
    def _get_quarter_dates(year, quarter):
        """
        Return start and end date for a calendar quarter.

        Q1 = Jan - Mar
        Q2 = Apr - Jun
        Q3 = Jul - Sep
        Q4 = Oct - Dec
        """
        quarter_months = {
            1: (1, 3),
            2: (4, 6),
            3: (7, 9),
            4: (10, 12),
        }

        start_month, end_month = quarter_months[quarter]

        start_date = date(year, start_month, 1)

        last_day = calendar.monthrange(year, end_month)[1]
        end_date = date(year, end_month, last_day)

        return start_date, end_date

    @staticmethod
    def _get_month_dates(year, month):
        """
        Return first and last date of a month.
        """
        first_day = date(year, month, 1)
        last_day = date(
            year,
            month,
            calendar.monthrange(year, month)[1]
        )

        return first_day, last_day

    @staticmethod
    def _get_working_days(start_date, end_date):
        """
        Count Monday-Friday working days.

        Saturday and Sunday are excluded.

        This is intentionally kept independent of attendance data
        because attendance is one of the inputs to the allocation
        formula.
        """
        if start_date > end_date:
            return 0

        working_days = 0
        current_date = start_date

        while current_date <= end_date:
            if current_date.weekday() < 5:
                working_days += 1

            current_date += timedelta(days=1)

        return working_days

    @staticmethod
    def _get_last_working_day(year, month):
        """
        Return the last Monday-Friday of the month.
        """
        last_day = date(
            year,
            month,
            calendar.monthrange(year, month)[1]
        )

        while last_day.weekday() >= 5:
            last_day -= timedelta(days=1)

        return last_day

    def _get_period_datetimes(self, start_date, end_date):
        """
        Convert dates to datetime range for Odoo searches.
        """
        start_datetime = datetime.combine(
            start_date,
            datetime.min.time()
        )

        end_datetime = datetime.combine(
            end_date + timedelta(days=1),
            datetime.min.time()
        )

        return start_datetime, end_datetime

    # =========================================================
    # ATTENDANCE DAYS
    # =========================================================

    def _get_attendance_days(self, start_date, end_date):
        """
        Count unique attendance dates for the employee.

        Multiple check-in/check-out records on the same day
        count as one attendance day.
        """
        self.ensure_one()

        start_datetime, end_datetime = self._get_period_datetimes(
            start_date,
            end_date
        )

        attendances = self.env['hr.attendance'].search([
            ('employee_id', '=', self.id),
            ('check_in', '>=', start_datetime),
            ('check_in', '<', end_datetime),
        ])

        attendance_dates = set()

        for attendance in attendances:
            if attendance.check_in:
                attendance_dates.add(
                    attendance.check_in.date()
                )

        return len(attendance_dates)

    # =========================================================
    # LEAVE DAYS
    # =========================================================

    def _get_leave_days(
        self,
        leave_type,
        start_date,
        end_date
    ):
        """
        Get approved leave days overlapping the requested period.

        Only validated leaves are considered.

        The calculation is limited to the overlap between the leave
        and the requested period.
        """
        self.ensure_one()

        if not leave_type:
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

            overlap_start = max(
                leave_start,
                start_date
            )

            overlap_end = min(
                leave_end,
                end_date
            )

            if overlap_start > overlap_end:
                continue

            # Prefer Odoo's calculated leave duration when the
            # entire leave is inside the requested period.
            if (
                leave_start >= start_date
                and leave_end <= end_date
                and getattr(leave, 'number_of_days', False)
            ):
                try:
                    total_days += float(
                        leave.number_of_days
                    )
                    continue
                except (TypeError, ValueError):
                    pass

            # Otherwise calculate overlapping calendar days.
            total_days += (
                overlap_end - overlap_start
            ).days + 1

        return total_days

    # =========================================================
    # FIND LEAVE TYPES
    # =========================================================

    def _get_leave_type_by_code(self, code):
        """
        Find leave type by custom time_off_code.
        """
        return self.env['hr.leave.type'].search(
            [('time_off_code', '=', code)],
            limit=1
        )

    # =========================================================
    # RH QUARTER
    # =========================================================

    @api.model
    def cron_allocate_rh(self):
        """
        RH Allocation Cron.

        RH is calculated only on the last working day of:
            March
            June
            September
            December

        Formula:

            RH =
                1 / working_days_in_quarter
                *
                (
                    attendance_days
                    + approved_EL_days
                    + approved_RH_days
                    + LWP_days
                )

        Existing/manual RH allocations are NOT used to calculate
        the current quarter's entitlement.

        This is important because RH before October may have been
        manually allocated.
        """

        today = date.today()

        # ---------------------------------------------------------
        # RH should run only on quarter-end last working day.
        # ---------------------------------------------------------

        quarter_end_months = [3, 6, 9, 12]

        if today.month not in quarter_end_months:
            return

        last_working_day = self._get_last_working_day(
            today.year,
            today.month
        )

        if today != last_working_day:
            return

        rh_type = self._get_leave_type_by_code('RH')
        el_type = self._get_leave_type_by_code('EL')
        lwp_type = self._get_leave_type_by_code('LWP')

        if not rh_type:
            _logger.warning(
                "RH leave type not found."
            )
            return

        # Determine current quarter.
        quarter = ((today.month - 1) // 3) + 1

        quarter_start, quarter_end = self._get_quarter_dates(
            today.year,
            quarter
        )

        employees = self.search([
            ('active', '=', True),
            ('emp_date_of_joining', '!=', False),
        ])

        for employee in employees:

            doj = employee.emp_date_of_joining

            # Employee joined after quarter end.
            if doj > quarter_end:
                continue

            # Start counting only from DOJ.
            period_start = max(
                doj,
                quarter_start
            )

            period_end = quarter_end

            if period_start > period_end:
                continue

            # -----------------------------------------------------
            # Working days
            # -----------------------------------------------------

            working_days = self._get_working_days(
                period_start,
                period_end
            )

            if working_days <= 0:
                continue

            # -----------------------------------------------------
            # Attendance
            # -----------------------------------------------------

            attendance_days = employee._get_attendance_days(
                period_start,
                period_end
            )

            # -----------------------------------------------------
            # Approved EL
            # -----------------------------------------------------

            el_applied_days = employee._get_leave_days(
                el_type,
                period_start,
                period_end
            )

            # -----------------------------------------------------
            # Approved RH
            # -----------------------------------------------------

            rh_applied_days = employee._get_leave_days(
                rh_type,
                period_start,
                period_end
            )

            # -----------------------------------------------------
            # Approved LWP
            # -----------------------------------------------------

            lwp_days = employee._get_leave_days(
                lwp_type,
                period_start,
                period_end
            )

            # -----------------------------------------------------
            # Formula
            # -----------------------------------------------------

            eligible_days = (
                attendance_days
                + el_applied_days
                + rh_applied_days
                + lwp_days
            )

            if eligible_days <= 0:
                _logger.info(
                    "RH skipped for %s: no eligible days.",
                    employee.name
                )
                continue

            rh_days = (
                1.0
                / float(working_days)
            ) * eligible_days

            # Round to 3 decimal places.
            rh_days = round(rh_days, 3)

            if rh_days <= 0:
                continue

            # -----------------------------------------------------
            # Unique quarter key
            # -----------------------------------------------------

            quarter_key = (
                f"{today.year}-Q{quarter}"
            )

            allocation_name = (
                f"RH Quarterly {quarter_key}"
            )

            # -----------------------------------------------------
            # Prevent duplicate allocation
            # -----------------------------------------------------

            existing = self.env[
                'hr.leave.allocation'
            ].search([
                ('employee_id', '=', employee.id),
                ('holiday_status_id', '=', rh_type.id),
                ('name', '=', allocation_name),
                ('state', '!=', 'refuse'),
            ], limit=1)

            if existing:
                continue

            # -----------------------------------------------------
            # Create RH allocation
            # -----------------------------------------------------

            allocation = self.env[
                'hr.leave.allocation'
            ].create({
                'name': allocation_name,
                'employee_id': employee.id,
                'holiday_status_id': rh_type.id,
                'number_of_days': rh_days,
            })

            allocation.action_approve()

            _logger.info(
                "RH allocated: Employee=%s | Quarter=%s | "
                "Working Days=%s | Attendance=%s | EL=%s | "
                "RH=%s | LWP=%s | Allocation=%s",
                employee.name,
                quarter_key,
                working_days,
                attendance_days,
                el_applied_days,
                rh_applied_days,
                lwp_days,
                rh_days,
            )

    # =========================================================
    # EL MONTHLY
    # =========================================================

    @api.model
    def cron_allocate_el(self):
        """
        EL Allocation Cron.

        EL is calculated on the last working day of every month.

        Formula:

            EL =
                1.5 / working_days_in_month
                *
                (
                    attendance_days
                    + approved_EL_days
                    + approved_RH_days
                    + LWP_days
                )
        """

        today = date.today()

        # ---------------------------------------------------------
        # Run only on last working day of month.
        # ---------------------------------------------------------

        last_working_day = self._get_last_working_day(
            today.year,
            today.month
        )

        if today != last_working_day:
            return

        el_type = self._get_leave_type_by_code('EL')
        rh_type = self._get_leave_type_by_code('RH')
        lwp_type = self._get_leave_type_by_code('LWP')

        if not el_type:
            _logger.warning(
                "EL leave type not found."
            )
            return

        # ---------------------------------------------------------
        # Current month
        # ---------------------------------------------------------

        month_start, month_end = self._get_month_dates(
            today.year,
            today.month
        )

        employees = self.search([
            ('active', '=', True),
            ('emp_date_of_joining', '!=', False),
        ])

        for employee in employees:

            doj = employee.emp_date_of_joining

            # Employee has not joined yet.
            if doj > month_end:
                continue

            # Start from DOJ if employee joined during month.
            period_start = max(
                doj,
                month_start
            )

            period_end = month_end

            if period_start > period_end:
                continue

            # -----------------------------------------------------
            # Working days
            # -----------------------------------------------------

            working_days = self._get_working_days(
                period_start,
                period_end
            )

            if working_days <= 0:
                continue

            # -----------------------------------------------------
            # Attendance
            # -----------------------------------------------------

            attendance_days = employee._get_attendance_days(
                period_start,
                period_end
            )

            # -----------------------------------------------------
            # Approved EL
            # -----------------------------------------------------

            el_applied_days = employee._get_leave_days(
                el_type,
                period_start,
                period_end
            )

            # -----------------------------------------------------
            # Approved RH
            # -----------------------------------------------------

            rh_applied_days = employee._get_leave_days(
                rh_type,
                period_start,
                period_end
            )

            # -----------------------------------------------------
            # Approved LWP
            # -----------------------------------------------------

            lwp_days = employee._get_leave_days(
                lwp_type,
                period_start,
                period_end
            )

            # -----------------------------------------------------
            # Formula
            # -----------------------------------------------------

            eligible_days = (
                attendance_days
                + el_applied_days
                + rh_applied_days
                + lwp_days
            )

            if eligible_days <= 0:
                _logger.info(
                    "EL skipped for %s: no eligible days.",
                    employee.name
                )
                continue

            el_days = (
                1.5
                / float(working_days)
            ) * eligible_days

            # Round to 3 decimal places.
            el_days = round(el_days, 3)

            if el_days <= 0:
                continue

            # -----------------------------------------------------
            # Unique monthly allocation
            # -----------------------------------------------------

            month_key = today.strftime('%Y-%m')

            allocation_name = (
                f"EL Monthly {month_key}"
            )

            existing = self.env[
                'hr.leave.allocation'
            ].search([
                ('employee_id', '=', employee.id),
                ('holiday_status_id', '=', el_type.id),
                ('name', '=', allocation_name),
                ('state', '!=', 'refuse'),
            ], limit=1)

            if existing:
                continue

            # -----------------------------------------------------
            # Create EL allocation
            # -----------------------------------------------------

            allocation = self.env[
                'hr.leave.allocation'
            ].create({
                'name': allocation_name,
                'employee_id': employee.id,
                'holiday_status_id': el_type.id,
                'number_of_days': el_days,
            })

            allocation.action_approve()

            _logger.info(
                "EL allocated: Employee=%s | Month=%s | "
                "Working Days=%s | Attendance=%s | EL=%s | "
                "RH=%s | LWP=%s | Allocation=%s",
                employee.name,
                month_key,
                working_days,
                attendance_days,
                el_applied_days,
                rh_applied_days,
                lwp_days,
                el_days,
            )