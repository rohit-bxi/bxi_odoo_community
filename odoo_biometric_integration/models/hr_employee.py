from datetime import datetime

import pytz

from odoo import models, fields, api

from .hr_attendance import EMPLOYEE_CHECKIN_MODES

WEEKDAY_LOCATION_FIELDS = (
    'monday_location_id', 'tuesday_location_id', 'wednesday_location_id', 'thursday_location_id',
    'friday_location_id', 'saturday_location_id', 'sunday_location_id',
)


class HrEmployeeInherit(models.Model):
    _inherit = 'hr.employee'

    device_id = fields.Many2one('essl.api.config')
    essl_emp_code = fields.Char(string='Biometric Employee Code', tracking=True)
    # No longer used: manual check in/out now follows the usual work location.
    # Kept so that upgrading does not drop the values already entered.
    work_location = fields.Selection([
        ('home', 'Work From Home'),
        ('office', 'Work From Office')
    ], string="Work Location (legacy)")
    essl_can_edit_device = fields.Boolean(compute='_compute_essl_can_edit_device')
    essl_manual_attendance_allowed = fields.Boolean(
        compute='_compute_essl_manual_attendance_allowed',
        help="False when the employee is linked to a biometric device (device and Biometric Employee Code set), "
             "today's usual work location is marked Biometric Attendance Only and no approved "
             "exception request covers today.")

    @api.depends_context('uid')
    def _compute_essl_can_edit_device(self):
        can_edit = self.env.user.has_group('hr.group_hr_manager')
        for employee in self:
            employee.essl_can_edit_device = can_edit

    def _compute_essl_manual_attendance_allowed(self):
        for employee in self:
            emp = employee.sudo()
            employee.essl_manual_attendance_allowed = (
                not (emp.device_id and emp.essl_emp_code)
                or not emp._essl_get_today_location().essl_biometric_only
                or emp._essl_has_exception_today()
                # an exception refused after a systray check-in must not strand it open
                or emp._essl_has_open_employee_attendance()
            )

    def _essl_get_today(self):
        return datetime.now(pytz.timezone(self.tz or 'Asia/Kolkata')).date()

    def _essl_has_exception_today(self):
        """Return whether an approved Exception request (bxi_shift_management) covers today.

        A Home request's compensation day is outside its From-To dates, so it does not count.
        """
        self.ensure_one()
        if 'bxi.shift.exception' not in self.env:
            return False
        today = self._essl_get_today()
        ShiftException = self.env['bxi.shift.exception'].sudo()
        domain = [
            ('employee_id', '=', self.id),
            ('state', '=', 'approved'),
            ('date_from', '<=', today),
            ('date_to', '>=', today),
        ]
        if 'category' in ShiftException._fields:
            domain.append(('category', '=', 'exception'))
        for exception in ShiftException.search(domain):
            if not exception.allowed_weekdays:
                return True
            try:
                weekdays = {int(day) for day in exception.allowed_weekdays.split(',') if day.strip()}
            except ValueError:
                continue
            if today.weekday() in weekdays:
                return True
        return False

    def _essl_has_open_employee_attendance(self):
        self.ensure_one()
        return self.attendance_state == 'checked_in' and self.last_attendance_id.in_mode in EMPLOYEE_CHECKIN_MODES

    def _essl_get_today_location(self):
        """Return the employee's usual work location for today, in their timezone."""
        self.ensure_one()
        today = self._essl_get_today()
        Attendance = self.env['hr.attendance']
        if hasattr(Attendance, '_get_effective_work_location'):
            # bxi_attendance: an approved shift exception first, then the weekday location
            return Attendance._get_effective_work_location(self, today) or self.env['hr.work.location']
        field_name = WEEKDAY_LOCATION_FIELDS[today.weekday()]
        if field_name in self._fields:
            return self[field_name]
        return self.work_location_id
