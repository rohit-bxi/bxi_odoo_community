# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

ATTENDANCE_ROLE_BAND_THRESHOLD = 8


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    latitude = fields.Float(string='Latitude', digits=(16, 8))
    longitude = fields.Float(string='Longitude', digits=(16, 8))
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

    def _validate_location_access(self, vals=None):
        """Require browser location permission before manual check-in/check-out."""
        if vals is None:
            vals = {}

        if vals.get('is_auto_checkout') is True:
            return

        if 'check_in' not in vals and 'check_out' not in vals:
            return

        latitude = vals.get('latitude')
        longitude = vals.get('longitude')

        if latitude is None and self.latitude:
            latitude = self.latitude
        if longitude is None and self.longitude:
            longitude = self.longitude

        if latitude in (None, False, 0.0) or longitude in (None, False, 0.0):
            raise UserError(_(
                "Please enable location access in Chrome or your browser before checking in or checking out."
            ))

    @api.model
    def create(self, vals_list):
        if not vals_list:
            return super().create(vals_list)

        if isinstance(vals_list, dict):
            vals_list = [vals_list]

        for vals in vals_list:
            employee_id = vals.get('employee_id')
            self._validate_attendance_eligibility(employee_id)
            self._validate_location_access(vals)

        return super().create(vals_list)

    def write(self, vals):
        if 'employee_id' in vals and vals.get('employee_id'):
            for rec in self:
                rec._validate_attendance_eligibility(vals.get('employee_id'))

        if any(field in vals for field in ('check_in', 'check_out', 'latitude', 'longitude')):
            for rec in self:
                update_vals = dict(vals)
                if 'latitude' not in update_vals and rec.latitude:
                    update_vals['latitude'] = rec.latitude
                if 'longitude' not in update_vals and rec.longitude:
                    update_vals['longitude'] = rec.longitude
                rec._validate_location_access(update_vals)

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
