# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

ATTENDANCE_ROLE_BAND_THRESHOLD = 8


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    is_auto_checkout = fields.Boolean(string='Auto Check-out', default=False)

    def _is_role_band_eligible_for_attendance(self, employee):
        """Allow attendance only for employees with role band below 8."""
        if not employee or not employee.role_band:
            return True

        role_band = str(employee.role_band).strip()
        if not role_band:
            return True

        try:
            parsed_value = float(role_band)
        except (TypeError, ValueError):
            return True

        return parsed_value < ATTENDANCE_ROLE_BAND_THRESHOLD

    def _validate_attendance_eligibility(self, employee_id):
        if not employee_id:
            return

        employee = self.env['hr.employee'].sudo().browse(employee_id)
        if employee and not self._is_role_band_eligible_for_attendance(employee):
            raise UserError(_(
                "Attendance is allowed only for employees whose role band is below %s. "
                "This employee is not eligible for attendance."
            ) % ATTENDANCE_ROLE_BAND_THRESHOLD)

    @api.model
    def create(self, vals):
        employee_id = vals.get('employee_id')
        self._validate_attendance_eligibility(employee_id)
        return super().create(vals)

    def write(self, vals):
        employee_id = vals.get('employee_id')
        if employee_id:
            self._validate_attendance_eligibility(employee_id)
        return super().write(vals)

    @api.model
    def _cron_auto_checkout(self):
        """
        Scheduled action to auto check-out all attendance records where check-out is missing.
        Runs daily at 11:50 PM and sets check_out to current time with is_auto_checkout=True.
        """
        open_attendances = self.search([('check_out', '=', False)])
        if open_attendances:
            now = fields.Datetime.now()
            open_attendances.write({
                'check_out': now,
                'is_auto_checkout': True,
            })
