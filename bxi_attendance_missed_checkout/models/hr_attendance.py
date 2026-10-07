# -*- coding: utf-8 -*-
import logging
from datetime import datetime, time, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _


_logger = logging.getLogger(__name__)

# Days of a month up to the cutoff belong to that month's attendance cycle:
# the cycle of October runs from 26 September to 25 October.
REGULARIZATION_CUTOFF_DAY = 25


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    is_missed_checkout = fields.Boolean(
        string='Missed Check-out', readonly=True, copy=False, index=True)
    lwp_leave_id = fields.Many2one(
        'hr.leave', string='LWP Leave', readonly=True, copy=False)
    missed_checkout_date = fields.Date(
        string='Missed Check-out Date', compute='_compute_missed_checkout_date')
    regularization_deadline = fields.Date(
        string='Regularization Deadline', compute='_compute_missed_checkout_date')

    @api.depends('check_in', 'employee_id')
    def _compute_missed_checkout_date(self):
        for attendance in self:
            local_date = (
                attendance._get_local_check_in_date()
                if attendance.check_in and attendance.employee_id else False
            )
            attendance.missed_checkout_date = local_date
            attendance.regularization_deadline = (
                self._get_regularization_cycle(local_date)[1] if local_date else False
            )

    # ============================================================
    # REGULARIZATION CYCLE
    # ============================================================

    @api.model
    def _get_regularization_cycle(self, ref_date):
        """(start, end) of the attendance cycle containing ref_date:
        the 26th of the previous month to the 25th of the month."""
        if ref_date.day > REGULARIZATION_CUTOFF_DAY:
            end = (ref_date + relativedelta(months=1)).replace(day=REGULARIZATION_CUTOFF_DAY)
        else:
            end = ref_date.replace(day=REGULARIZATION_CUTOFF_DAY)
        start = (end - relativedelta(months=1)).replace(day=REGULARIZATION_CUTOFF_DAY + 1)
        return start, end

    @api.model
    def _get_last_closed_regularization_cycle(self, today):
        """(start, end) of the most recent cycle whose cutoff has passed."""
        open_start = self._get_regularization_cycle(today)[0]
        return self._get_regularization_cycle(open_start - timedelta(days=1))

    @api.model
    def _get_regularization_today(self):
        """Today in the timezone of the company working schedule, not of
        the user running the cron, so the cutoff day does not shift."""
        tz_name = (
            self.env.company.resource_calendar_id.tz
            or self.env.user.tz
            or 'Asia/Kolkata'
        )
        try:
            tz = pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            tz = pytz.timezone('Asia/Kolkata')
        return datetime.now(tz).date()

    # ============================================================
    # HELPERS
    # ============================================================

    def _get_local_check_in_date(self):
        self.ensure_one()
        return self._get_employee_local_datetime(
            self.employee_id, self.check_in).date()

    @api.model
    def _get_stale_open_attendances(self, employees, reference_dt=None):
        """
        Open attendances of ``employees`` whose local check-in date is
        before the employee's local date at ``reference_dt`` (default now).
        """
        if not employees:
            return self.browse()

        reference_dt = reference_dt or fields.Datetime.now()

        open_attendances = self.sudo().search([
            ('employee_id', 'in', employees.ids),
            ('check_out', '=', False),
        ])

        return open_attendances.filtered(
            lambda att: att._get_local_check_in_date()
            < att._get_employee_local_datetime(att.employee_id, reference_dt).date()
        )

    def _is_employee_working_day(self, employee, local_date):
        """True if the employee's calendar has working time on the date,
        public holidays and validated leaves excluded."""
        local_now = self._get_employee_local_datetime(employee, fields.Datetime.now())
        tz = pytz.timezone(local_now.tzinfo.zone)

        day_start = tz.localize(datetime.combine(local_date, time.min))
        day_end = tz.localize(datetime.combine(local_date, time.max))

        data = employee._get_work_days_data_batch(
            day_start, day_end, compute_leaves=True
        ).get(employee.id, {})

        return data.get('days', 0) > 0

    # ============================================================
    # LWP RULES
    # ============================================================

    def _is_missed_checkout_lwp_applicable(self, employee, local_date):
        """Return (applicable, reason)."""
        company = employee.company_id

        if not company.missed_checkout_lwp:
            return False, _('LWP on missed check-out is disabled')

        if (
            company.missed_checkout_lwp_start_date
            and local_date < company.missed_checkout_lwp_start_date
        ):
            return False, _('check-in date is before the LWP start date')

        if (
            company.attendance_regularization_start_date
            and local_date < company.attendance_regularization_start_date
        ):
            return False, _('date is before the attendance regularization start date')

        if 'is_on_deputation' in employee._fields and employee.is_on_deputation:
            return False, _('employee is on deputation')

        # False for an approved client-site exception or no location.
        work_location = self._get_effective_work_location(employee, local_date)
        if not work_location or not (work_location.office or work_location.home):
            return False, _('not an office or home working day')

        existing_leave = self.env['hr.leave'].sudo().search_count([
            ('employee_id', '=', employee.id),
            ('request_date_from', '<=', local_date),
            ('request_date_to', '>=', local_date),
            ('state', 'not in', ('refuse', 'cancel')),
        ])
        if existing_leave:
            return False, _('a time off already exists for that day')

        if not self._is_employee_working_day(employee, local_date):
            return False, _('non-working day or public holiday')

        return True, ''

    @api.model
    def _create_missed_checkout_lwp(self, employee, local_date):
        """Create and validate a full-day LWP for a day without attendance
        regularization. Neither the manager nor HR is notified.
        Return (leave, reason) where reason explains a skipped LWP."""
        Leave = self.env['hr.leave']

        applicable, reason = self._is_missed_checkout_lwp_applicable(employee, local_date)
        if not applicable:
            _logger.info(
                "Missed attendance without LWP | employee=%s | date=%s | reason=%s",
                employee.name, local_date, reason,
            )
            return Leave, reason

        # leave_fast_create: no manager follower and no approval activity
        Leave = Leave.sudo().with_company(employee.company_id).with_context(
            skip_sick_leave_policy=True,
            skip_leave_submission_email=True,
            mail_activity_automation_skip=True,
            leave_fast_create=True,
            tracking_disable=True,
            mail_create_nosubscribe=True,
            mail_create_nolog=True,
            mail_notrack=True,
        )

        lwp_type = Leave._get_leave_type_by_code('LWP')
        if not lwp_type:
            _logger.error(
                "Missed attendance: LWP time off type (code LWP) is not "
                "configured for company %s | employee=%s | date=%s",
                employee.company_id.name, employee.name, local_date,
            )
            return self.env['hr.leave'], _('LWP time off type is not configured')

        leave = Leave.create({
            'name': _('LWP - Attendance not regularized on %s') % local_date.strftime('%d-%m-%Y'),
            'employee_id': employee.id,
            'holiday_status_id': lwp_type.id,
            'request_date_from': local_date,
            'request_date_to': local_date,
            'is_missed_checkout_lwp': True,
        })

        leave.action_approve(check_state=False)
        if leave.state == 'validate1':
            leave._action_validate(check_state=False)

        _logger.info(
            "Missed attendance LWP created | employee=%s | date=%s | leave=%s",
            employee.name, local_date, leave.id,
        )
        return leave, ''

    # ============================================================
    # CLOSE MISSED CHECK-OUT
    # ============================================================

    def _close_missed_checkout(self):
        """Close the forgotten attendance with zero duration. The LWP is only
        applied at the monthly cutoff if the day is not regularized."""
        for attendance in self.sudo():
            if attendance.check_out:
                continue

            local_date = attendance._get_local_check_in_date()

            # is_auto_checkout bypasses the GPS validation of bxi_attendance.
            attendance.write({
                'check_out': attendance.check_in,
                'is_auto_checkout': True,
                'is_missed_checkout': True,
                'out_mode': 'auto_check_out',
            })

            applicable, reason = attendance._is_missed_checkout_lwp_applicable(
                attendance.employee_id, local_date)
            if applicable:
                attendance.message_post(body=_(
                    "No check-out was recorded on %(date)s. The attendance was "
                    "closed automatically. Without an approved attendance "
                    "regularization by the 25th, a full-day LWP is applied.",
                    date=local_date.strftime('%d-%m-%Y'),
                ))
                attendance._send_missed_checkout_mail()
            else:
                attendance.message_post(body=_(
                    "No check-out was recorded on %(date)s. The attendance was "
                    "closed automatically without LWP (%(reason)s).",
                    date=local_date.strftime('%d-%m-%Y'),
                    reason=reason,
                ))

    def _send_missed_checkout_mail(self):
        """Ask the employee only to regularize the day."""
        template = self.env.ref(
            'bxi_attendance_missed_checkout.mail_template_missed_checkout_regularization',
            raise_if_not_found=False,
        )
        if not template:
            return
        for attendance in self:
            if attendance.employee_id.work_email:
                template.sudo().send_mail(attendance.id, force_send=False)

    # ============================================================
    # CRON
    # ============================================================

    @api.model
    def _cron_process_missed_checkouts(self):
        open_attendances = self.sudo().search([('check_out', '=', False)])
        stale = self._get_stale_open_attendances(open_attendances.employee_id)

        for attendance in stale:
            try:
                with self.env.cr.savepoint():
                    attendance._close_missed_checkout()
            except Exception:
                _logger.exception(
                    "Missed check-out processing failed | attendance=%s | employee=%s",
                    attendance.id, attendance.employee_id.name,
                )

    @api.model
    def _cron_auto_checkout(self):
        # Replaces bxi_attendance behaviour of closing every open
        # attendance with the current time.
        return self._cron_process_missed_checkouts()

    # ============================================================
    # CREATE
    # ============================================================

    @api.model_create_multi
    def create(self, vals_list):

        if isinstance(vals_list, dict):
            vals_list = [vals_list]

        # A new check-in (API, manual) closes the employee's forgotten
        # attendance of a previous day first, otherwise the core
        # "hasn't checked out since" constraint blocks it.
        for vals in vals_list:
            if (
                vals.get('employee_id')
                and vals.get('check_in')
                and not vals.get('check_out')
            ):
                employee = self.env['hr.employee'].sudo().browse(vals['employee_id']).exists()
                if employee:
                    check_in = fields.Datetime.to_datetime(vals['check_in'])
                    self._get_stale_open_attendances(employee, check_in)._close_missed_checkout()

        return super().create(vals_list)
