# -*- coding: utf-8 -*-
from datetime import datetime
from venv import logger

import pytz
import math
from odoo import models, fields, api, _
from odoo.exceptions import UserError

ATTENDANCE_ROLE_BAND_THRESHOLD = 8


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    state = fields.Selection([
        ('draft', 'Draft'),
        ('level_1_late', 'Level 1 Late'),
        ('level_2_late', 'Level 2 Late'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Stage', default='draft', copy=False, index=True)

    # Approver Details
    approved_by_id = fields.Many2one('hr.employee', string='Approved By', readonly=True, copy=False)
    approved_emp_code = fields.Char(string='Approver Employee Code', compute='_compute_approved_emp_code', store=True, readonly=True)
    approved_datetime = fields.Datetime(string='Approval Date & Time', readonly=True, copy=False)
    approval_remark = fields.Text(string='Approval Remark', copy=False)

    # Rejection Details
    rejected_by_id = fields.Many2one('hr.employee', string='Rejected By', readonly=True, copy=False)
    rejected_emp_code = fields.Char(string='Rejector Employee Code', compute='_compute_rejected_emp_code', store=True, readonly=True)
    rejected_datetime = fields.Datetime(string='Rejection Date & Time', readonly=True, copy=False)
    rejection_remark = fields.Text(string='Rejection Remark', copy=False)
    latitude = fields.Float(string='Latitude', digits=(16, 8))
    longitude = fields.Float(string='Longitude', digits=(16, 8))
    is_auto_checkout = fields.Boolean(string='Auto Check-out', default=False)

    @api.depends('approved_by_id')
    def _compute_approved_emp_code(self):
        for rec in self:
            rec.approved_emp_code = getattr(rec.approved_by_id, 'employee_code', False) or ''

    @api.depends('rejected_by_id')
    def _compute_rejected_emp_code(self):
        for rec in self:
            rec.rejected_emp_code = getattr(rec.rejected_by_id, 'employee_code', False) or ''

    def _get_current_employee(self):
        user = self.env.user
        emp = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not emp and user.email:
            emp = self.env['hr.employee'].sudo().search([('work_email', '=', user.email)], limit=1)
        return emp

    def _evaluate_attendance_stage(self):
        """
        Check check-in time against employee's working schedule (resource.calendar).
        - If check-in is on or before shift start time -> set stage to 'approved'.
        - If check-in is after shift start time but before break time -> set stage to 'level_1_late'.
        - If check-in is on or after break start time -> set stage to 'level_2_late'.
        """
        for rec in self:
            if not rec.check_in or not rec.employee_id:
                continue

            tz_name = rec.employee_id.tz or (rec.employee_id.user_id and rec.employee_id.user_id.tz) or rec.env.user.tz or 'Asia/Kolkata'
            try:
                tz = pytz.timezone(tz_name)
            except Exception:
                tz = pytz.timezone('Asia/Kolkata')

            dt_utc = pytz.utc.localize(rec.check_in) if not rec.check_in.tzinfo else rec.check_in
            local_dt = dt_utc.astimezone(tz)
            local_date = local_dt.date()
            local_weekday = str(local_dt.weekday())  # '0'=Mon, ..., '6'=Sun
            local_time_hours = local_dt.hour + (local_dt.minute / 60.0) + (local_dt.second / 3600.0)

            calendar = rec.employee_id.resource_calendar_id or rec.employee_id.company_id.resource_calendar_id
            if not calendar:
                rec.state = 'approved'
                continue

            day_atts = calendar.attendance_ids.filtered(lambda a: a.dayofweek == local_weekday)
            if 'date_from' in day_atts._fields:
                day_atts = day_atts.filtered(
                    lambda a: (not a.date_from or a.date_from <= local_date) and
                              (not a.date_to or a.date_to >= local_date)
                )

            if not day_atts:
                rec.state = 'approved'
                continue

            sorted_atts = day_atts.sorted('hour_from')
            shift_start_hour = sorted_atts[0].hour_from

            if len(sorted_atts) > 1:
                # Break starts at the end of the first work period (e.g. 13:00 for 9-13, 14-18)
                break_start_hour = sorted_atts[0].hour_to
            else:
                # For a single continuous block (e.g. 9-18), break starts at the mid-day point
                single_att = sorted_atts[0]
                total_duration = single_att.hour_to - single_att.hour_from
                break_start_hour = single_att.hour_from + (total_duration / 2.0)

            if local_time_hours <= (shift_start_hour + 0.0001):
                rec.state = 'approved'
            elif local_time_hours >= (break_start_hour - 0.0001):
                rec.state = 'level_2_late'
            else:
                rec.state = 'level_1_late'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._evaluate_attendance_stage()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'check_in' in vals or 'employee_id' in vals:
            self._evaluate_attendance_stage()
        return res

    def action_set_draft(self):
        self.write({'state': 'draft'})

    def action_level_1_late(self):
        self.write({'state': 'level_1_late'})

    def action_level_2_late(self):
        self.write({'state': 'level_2_late'})

    def action_approve(self):
        current_emp = self._get_current_employee()
        self.write({
            'state': 'approved',
            'approved_by_id': current_emp.id if current_emp else False,
            'approved_datetime': fields.Datetime.now(),
        })

    def action_reject(self):
        current_emp = self._get_current_employee()
        self.write({
            'state': 'rejected',
            'rejected_by_id': current_emp.id if current_emp else False,
            'rejected_datetime': fields.Datetime.now(),
        })

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

    def _get_effective_work_location(self, employee, check_date):
        """
        Return the work location that should be used for geofence validation
        for the employee on the given date.

        Priority:

        1. Approved Shift Exception covering this date and weekday
        2. Employee's usual weekday work location

        IMPORTANT:
        This method DOES NOT modify the employee's normal Monday-Sunday
        location fields.

        Example:

            Tuesday employee location = Udaipur

            Approved exception:
                08-Sep-2026 to 10-Sep-2026
                Tue, Wed, Thu
                To Location = Jaipur

            Result:
                Tuesday  -> Jaipur
                Wednesday -> Jaipur
                Thursday -> Jaipur
                Friday -> employee Friday location
        """

        if not employee or not check_date:
            return False

        # 0. Per-day override created by approved exceptions
        EmployeeDayLocation = self.env.get('bxi.shift.employee.location')
        if EmployeeDayLocation:
            try:
                per_day = EmployeeDayLocation.sudo().search([
                    ('employee_id', '=', employee.id),
                    ('date', '=', check_date),
                ], limit=1)
                if per_day and per_day.location_id:
                    return per_day.location_id
            except Exception:
                pass

        ShiftException = self.env["bxi.shift.exception"].sudo()
        exceptions = ShiftException.search(
            [
                ("employee_id", "=", employee.id),
                ("state", "=", "approved"),
                ("date_from", "<=", check_date),
                ("date_to", ">=", check_date),
            ],
            order="id desc",
        )

        for exception in exceptions:
            if exception.allowed_weekdays:
                try:
                    allowed_weekdays = [
                        int(value.strip())
                        for value in exception.allowed_weekdays.split(",")
                        if value.strip()
                    ]
                except (TypeError, ValueError):
                    logger.warning(
                        "Invalid allowed_weekdays '%s' on Shift Exception %s",
                        exception.allowed_weekdays,
                        exception.name,
                    )
                    continue
                allowed_weekdays = [
                    day
                    for day in allowed_weekdays
                    if 0 <= day <= 6
                ]

                if check_date.weekday() not in allowed_weekdays:
                    continue

            # Approved exception applies today.
            if exception.to_location_id:
                logger.info(
                    "Attendance location override applied | "
                    "employee=%s | date=%s | exception=%s | location=%s",
                    employee.name,
                    check_date,
                    exception.name,
                    exception.to_location_id.name,
                )

                return exception.to_location_id

        # ---------------------------------------------------------------------
        # 2. No applicable exception
        #    Use employee's normal/usual weekday location.
        # ---------------------------------------------------------------------
        weekday_location_fields = {
            0: "monday_location_id",
            1: "tuesday_location_id",
            2: "wednesday_location_id",
            3: "thursday_location_id",
            4: "friday_location_id",
            5: "saturday_location_id",
            6: "sunday_location_id",
        }
        field_name = weekday_location_fields.get(check_date.weekday())

        if not field_name:
            return False

        if field_name not in employee._fields:
            logger.warning(
                "Employee model does not contain location field '%s'",
                field_name,
            )
            return False

        return employee[field_name]


    def _validate_location_access(self, vals=None):
        """
        Validate attendance GPS against the employee's effective work location.
        Effective work location:
            Approved Shift Exception
                    ↓
            Employee normal weekday location

        The employee's normal location fields are NEVER changed.

        Home/Remote locations bypass geofencing.
        """

        if vals is None:
            vals = {}

        # ---------------------------------------------------------------------
        # Automatic checkout should never be blocked by geofence validation.
        # ---------------------------------------------------------------------

        if vals.get("is_auto_checkout") is True:
            return

        # ---------------------------------------------------------------------
        # Only validate check-in/check-out operations.
        # ---------------------------------------------------------------------

        if "check_in" not in vals and "check_out" not in vals:
            return

        # ---------------------------------------------------------------------
        # Check whether geographic information was actually submitted.
        # ---------------------------------------------------------------------

        geo_keys = (
            "latitude",
            "longitude",
            "location",
            "geo_location",
            "geoip",
            "in_latitude",
            "in_longitude",
            "out_latitude",
            "out_longitude",
        )

        if not any(key in vals for key in geo_keys):
            return

        # ---------------------------------------------------------------------
        # Read latitude / longitude.
        # ---------------------------------------------------------------------

        latitude = vals.get(
            "latitude",
            vals.get("in_latitude"),
        )

        longitude = vals.get(
            "longitude",
            vals.get("in_longitude"),
        )

        # Checkout fallback.
        if "out_latitude" in vals and not latitude:
            latitude = vals.get("out_latitude")

        if "out_longitude" in vals and not longitude:
            longitude = vals.get("out_longitude")

        # ---------------------------------------------------------------------
        # Support location as dict/list/tuple.
        # ---------------------------------------------------------------------

        location = vals.get("location")

        if location:

            if isinstance(location, dict):

                latitude = location.get(
                    "latitude",
                    latitude,
                )

                longitude = location.get(
                    "longitude",
                    longitude,
                )

            elif isinstance(location, (list, tuple)) and len(location) >= 2:

                latitude = location[0]
                longitude = location[1]

        # ---------------------------------------------------------------------
        # GPS is required when geo fields were explicitly supplied.
        # ---------------------------------------------------------------------

        if latitude in (None, False, "") or longitude in (
            None,
            False,
            "",
        ):
            raise UserError(
                _(
                    "Please enable location access in Chrome or your "
                    "browser before checking in or checking out."
                )
            )

        # ---------------------------------------------------------------------
        # 0,0 is treated as invalid GPS.
        # ---------------------------------------------------------------------

        try:
            latitude = float(latitude)
            longitude = float(longitude)

        except (TypeError, ValueError):
            raise UserError(
                _(
                    "The GPS coordinates received from your browser "
                    "are invalid. Please enable location access and try again."
                )
            )

        if latitude == 0.0 and longitude == 0.0:
            raise UserError(
                _(
                    "Please enable location access in Chrome or your "
                    "browser before checking in or checking out."
                )
            )

        # ---------------------------------------------------------------------
        # Employee
        # ---------------------------------------------------------------------

        employee_id = vals.get("employee_id")

        if not employee_id:
            return

        employee = (
            self.env["hr.employee"]
            .sudo()
            .browse(employee_id)
            .exists()
        )

        if not employee:
            return

        # ---------------------------------------------------------------------
        # Determine attendance date.
        # ---------------------------------------------------------------------

        check_dt = (
            vals.get("check_in")
            or vals.get("check_out")
        )

        if not check_dt:
            check_dt = fields.Datetime.now()

        # Odoo normally gives a datetime object here.
        # Add support for a string just in case an API sends one.
        if isinstance(check_dt, str):

            try:
                check_dt = fields.Datetime.to_datetime(check_dt)
            except Exception:
                return

        if not isinstance(check_dt, datetime):
            return

        # ---------------------------------------------------------------------
        # Convert UTC datetime to employee's local timezone.
        # ---------------------------------------------------------------------

        tz_name = (
            employee.tz
            or (employee.user_id and employee.user_id.tz)
            or self.env.user.tz
            or "Asia/Kolkata"
        )

        try:
            employee_tz = pytz.timezone(tz_name)
        except Exception:
            employee_tz = pytz.timezone("Asia/Kolkata")

        if check_dt.tzinfo:
            utc_dt = check_dt.astimezone(pytz.utc)
        else:
            utc_dt = pytz.utc.localize(check_dt)

        local_dt = utc_dt.astimezone(employee_tz)

        local_date = local_dt.date()

        # ---------------------------------------------------------------------
        # Determine effective work location.
        # ---------------------------------------------------------------------

        work_location = self._get_effective_work_location(
            employee,
            local_date,
        )

        # No work location configured.
        # No geofence is enforced.
        if not work_location:
            logger.info(
                "No work location configured for employee %s on %s. "
                "Attendance allowed without geofence.",
                employee.name,
                local_date,
            )
            return

        # ---------------------------------------------------------------------
        # Home / Remote should allow attendance from anywhere.
        # ---------------------------------------------------------------------

        location_type = getattr(
            work_location,
            "location_type",
            False,
        )

        if location_type and str(location_type).lower() in (
            "home",
            "remote",
        ):
            logger.info(
                "Home/Remote location '%s' for employee %s. "
                "Geofence skipped.",
                work_location.name,
                employee.name,
            )
            return

        # ---------------------------------------------------------------------
        # Work location master coordinates.
        # ---------------------------------------------------------------------

        location_latitude = getattr(
            work_location,
            "latitude",
            None,
        )

        location_longitude = getattr(
            work_location,
            "longitude",
            None,
        )

        radius_km = (
            getattr(
                work_location,
                "radius_km",
                2.5,
            )
            or 2.5
        )

        if location_latitude in (
            None,
            False,
            "",
        ) or location_longitude in (
            None,
            False,
            "",
        ):
            logger.warning(
                "Work location '%s' has no GPS coordinates. "
                "Attendance allowed without geofence.",
                work_location.name,
            )
            return

        # ---------------------------------------------------------------------
        # Haversine distance.
        # ---------------------------------------------------------------------

        def haversine(lat1, lon1, lat2, lon2):
            radius_earth_km = 6371.0

            phi1 = math.radians(float(lat1))
            phi2 = math.radians(float(lat2))

            delta_phi = math.radians(
                float(lat2) - float(lat1)
            )

            delta_lambda = math.radians(
                float(lon2) - float(lon1)
            )

            a = (
                math.sin(delta_phi / 2.0) ** 2
                + math.cos(phi1)
                * math.cos(phi2)
                * math.sin(delta_lambda / 2.0) ** 2
            )

            c = 2 * math.atan2(
                math.sqrt(a),
                math.sqrt(1 - a),
            )

            return radius_earth_km * c

        try:
            distance_km = haversine(
                location_latitude,
                location_longitude,
                latitude,
                longitude,
            )

            allowed_radius = float(radius_km)

        except (TypeError, ValueError):
            logger.exception(
                "Unable to calculate geofence distance for employee %s",
                employee.name,
            )
            return

        # ---------------------------------------------------------------------
        # BLOCK attendance if outside geofence.
        # ---------------------------------------------------------------------

        if distance_km > allowed_radius + 0.0001:

            raise UserError(
                _(
                    "Your current location is %.2f km away from the "
                    "assigned work location '%s' (allowed %.2f km). "
                    "Attendance is not allowed."
                )
                % (
                    distance_km,
                    work_location.name or "work location",
                    allowed_radius,
                )
            )

        logger.info(
            "Attendance location validated | employee=%s | date=%s | "
            "location=%s | distance=%.2f km | allowed=%.2f km",
            employee.name,
            local_date,
            work_location.name,
            distance_km,
            allowed_radius,
        )

    # -------------------------------------------------------------------------
    # CREATE
    # -------------------------------------------------------------------------

    @api.model_create_multi
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