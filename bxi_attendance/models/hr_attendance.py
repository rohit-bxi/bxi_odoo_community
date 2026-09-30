import logging
import math
from datetime import datetime

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)

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
    is_missed_checkout = fields.Boolean(
        string='Missed Checkout', default=False, copy=False, index=True
    )
    lwp_leave_id = fields.Many2one(
        'hr.leave', string='Missed Checkout LWP', readonly=True, copy=False
    )
    missed_checkout_email_sent = fields.Boolean(
        string='Missed Checkout Email Sent', default=False, copy=False
    )

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

        employee = self.env["hr.employee"].sudo().search(
            [
                ("user_id", "=", user.id),
            ],
            limit=1,
        )

        if not employee and user.email:
            employee = self.env["hr.employee"].sudo().search(
                [
                    ("work_email", "=", user.email),
                ],
                limit=1,
            )

        return employee

    # ============================================================
    # ATTENDANCE ELIGIBILITY

    # ============================================================

    def _is_role_band_eligible_for_attendance(self, employee):
        """
        Attendance is allowed only for role bands below 8.
        """
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
        employee = (
            self.env["hr.employee"]
            .sudo()
            .browse(employee_id)
            .exists()
        )
        if (
            employee
            and not self._is_role_band_eligible_for_attendance(employee)
        ):
            raise UserError(
                _(
                    "Attendance is allowed only for employees "
                    "whose role band is below %s."
                )
                % ATTENDANCE_ROLE_BAND_THRESHOLD
            )

    # ============================================================
    # EMPLOYEE DAY LOCATION

    # ============================================================

    def _get_employee_day_location(self, employee, check_date):
        """
        Get the employee's configured work location for the
        particular date.
        Monday    -> monday_location_id
        Tuesday   -> tuesday_location_id
        Wednesday -> wednesday_location_id
        Thursday  -> thursday_location_id
        Friday    -> friday_location_id
        Saturday  -> saturday_location_id
        Sunday    -> sunday_location_id
        """
        if not employee or not check_date:
            return False
        weekday_location_fields = {
            0: "monday_location_id",
            1: "tuesday_location_id",
            2: "wednesday_location_id",
            3: "thursday_location_id",
            4: "friday_location_id",
            5: "saturday_location_id",
            6: "sunday_location_id",
        }
        field_name = weekday_location_fields.get(
            check_date.weekday()
        )
        if not field_name:
            return False
        if field_name not in employee._fields:
            _logger.warning(
                "Employee model does not contain field %s",
                field_name,
            )
            return False
        return employee[field_name]

    # ============================================================
    # EFFECTIVE WORK LOCATION

    # ============================================================

    def _get_effective_work_location(
        self,
        employee,
        check_date,
    ):
        """
        Determine the effective work location.
        Priority:
        1. Approved Shift Exception
        2. Employee weekday location
        IMPORTANT:
        Employee weekday location fields are the normal source
        of truth.
        Shift exception can temporarily override the location
        for an approved exception.
        """
        if not employee or not check_date:
            return False
        # --------------------------------------------------------
        # 1. Approved shift exception
        # --------------------------------------------------------
        if "bxi.shift.exception" in self.env:
            ShiftException = self.env[
                "bxi.shift.exception"
            ].sudo()
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
                allowed_weekdays_value = getattr(
                    exception,
                    "allowed_weekdays",
                    False,
                )
                # If weekdays are specified, verify the current
                # day is included.
                if allowed_weekdays_value:
                    try:
                        allowed_weekdays = [
                            int(value.strip())
                            for value in
                            allowed_weekdays_value.split(",")
                            if value.strip()
                        ]
                    except (TypeError, ValueError):
                        _logger.warning(
                            "Invalid allowed_weekdays '%s' "
                            "on exception %s",
                            allowed_weekdays_value,
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
                if exception.mode == "client":
                    _logger.info(
                        "Approved client-site exception applied | "
                        "employee=%s | date=%s | exception=%s | "
                        "location tracking bypassed",
                        employee.name,
                        check_date,
                        exception.name,
                    )
                    return False
                if exception.to_location_id:
                    _logger.info(
                        "Approved shift exception applied | "
                        "employee=%s | date=%s | exception=%s | "
                        "location=%s",
                        employee.name,
                        check_date,
                        exception.name,
                        exception.to_location_id.name,
                    )
                    return exception.to_location_id
        # --------------------------------------------------------
        # 2. Employee's normal weekday location
        # --------------------------------------------------------
        return self._get_employee_day_location(
            employee,
            check_date,
        )

    # ============================================================
    # TIMEZONE

    # ============================================================

    def _get_employee_local_datetime(
        self,
        employee,
        check_datetime,
    ):
        """
        Convert UTC datetime to employee local timezone.
        """
        tz_name = (
            employee.tz
            or (
                employee.user_id
                and employee.user_id.tz
            )
            or self.env.user.tz
            or "Asia/Kolkata"
        )
        try:
            employee_tz = pytz.timezone(tz_name)
        except Exception:
            employee_tz = pytz.timezone("Asia/Kolkata")
        if check_datetime.tzinfo:
            utc_datetime = check_datetime.astimezone(
                pytz.utc
            )
        else:
            utc_datetime = pytz.utc.localize(
                check_datetime
            )
        return utc_datetime.astimezone(employee_tz)

    # ============================================================
    # GPS DISTANCE

    # ============================================================

    @staticmethod
    def _calculate_distance_km(
        latitude1,
        longitude1,
        latitude2,
        longitude2,
    ):
        """
        Calculate distance between two GPS coordinates
        using the Haversine formula.
        """
        earth_radius_km = 6371.0
        lat1 = math.radians(float(latitude1))
        lat2 = math.radians(float(latitude2))
        delta_lat = math.radians(
            float(latitude2) - float(latitude1)
        )
        delta_lon = math.radians(
            float(longitude2) - float(longitude1)
        )
        a = (
            math.sin(delta_lat / 2.0) ** 2
            +
            math.cos(lat1)
            *
            math.cos(lat2)
            *
            math.sin(delta_lon / 2.0) ** 2
        )
        c = 2 * math.atan2(
            math.sqrt(a),
            math.sqrt(1 - a),
        )
        return earth_radius_km * c

    # ============================================================
    # GPS VALIDATION

    # ============================================================

    def _validate_location_access(self, vals=None):
        if vals is None:
            vals = {}
        # --------------------------------------------------------
        # Auto checkout
        # --------------------------------------------------------
        if vals.get("is_auto_checkout") is True:
            return
        # --------------------------------------------------------
        # Determine operation
        # --------------------------------------------------------
        is_checkin = "check_in" in vals
        is_checkout = "check_out" in vals
        if not is_checkin and not is_checkout:
            return
        # --------------------------------------------------------
        # Employee
        # --------------------------------------------------------
        employee_id = vals.get("employee_id")
        # For checkout, employee_id is normally not present in vals
        # because we are updating an existing attendance record.
        if not employee_id and self:
            employee_id = self[:1].employee_id.id
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
        # --------------------------------------------------------
        # Determine GPS coordinates
        # --------------------------------------------------------
        latitude = False
        longitude = False
        if is_checkin:
            latitude = vals.get(
                "latitude"
            )
            longitude = vals.get(
                "longitude"
            )
            # API compatibility
            if latitude in (None, False, ""):
                latitude = vals.get(
                    "in_latitude"
                )
            if longitude in (None, False, ""):
                longitude = vals.get(
                    "in_longitude"
                )
        elif is_checkout:
            latitude = vals.get(
                "out_latitude"
            )
            longitude = vals.get(
                "out_longitude"
            )
            # Generic GPS fields
            if latitude in (None, False, ""):
                latitude = vals.get(
                    "latitude"
                )
            if longitude in (None, False, ""):
                longitude = vals.get(
                    "longitude"
                )
        # --------------------------------------------------------
        # Support location dictionary
        # --------------------------------------------------------
        location = vals.get("location")
        if location and isinstance(location, dict):
            latitude = location.get(
                "latitude",
                latitude,
            )
            longitude = location.get(
                "longitude",
                longitude,
            )
        elif (
            location
            and isinstance(location, (list, tuple))
            and len(location) >= 2
        ):
            latitude = location[0]
            longitude = location[1]
        # --------------------------------------------------------
        # GPS is mandatory for actual check-in/check-out
        # --------------------------------------------------------
        if latitude in (None, False, "") or longitude in (
            None,
            False,
            "",
        ):
            raise UserError(
                _(
                    "GPS location is required for "
                    "check-in/check-out. Please enable "
                    "location access in your browser and try again."
                )
            )
        # --------------------------------------------------------
        # Convert GPS to float
        # --------------------------------------------------------
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError):
            raise UserError(
                _(
                    "The GPS coordinates received from your "
                    "browser are invalid. Please enable "
                    "location access and try again."
                )
            )
        # --------------------------------------------------------
        # Invalid GPS
        # --------------------------------------------------------
        if latitude == 0.0 and longitude == 0.0:
            raise UserError(
                _(
                    "Invalid GPS coordinates received. "
                    "Please enable location access and try again."
                )
            )
        # --------------------------------------------------------
        # Determine check datetime
        # --------------------------------------------------------
        if is_checkin:
            check_datetime = vals.get(
                "check_in"
            )
        else:
            check_datetime = vals.get(
                "check_out"
            )
        if not check_datetime:
            check_datetime = fields.Datetime.now()
        # --------------------------------------------------------
        # Convert string datetime if required
        # --------------------------------------------------------
        if isinstance(check_datetime, str):
            try:
                check_datetime = fields.Datetime.to_datetime(
                    check_datetime
                )
            except Exception:
                raise UserError(
                    _(
                        "Invalid attendance date/time."
                    )
                )
        if not isinstance(check_datetime, datetime):
            raise UserError(
                _("Invalid attendance date/time.")
            )
        # --------------------------------------------------------
        # Employee local date
        # --------------------------------------------------------
        # Checkout must use the SAME work-location date as the check-in.
        # This prevents a late/manual checkout from switching to the next
        # weekday's configured location.
        location_datetime = check_datetime
        if is_checkout and self[:1] and self[:1].check_in:
            location_datetime = self[:1].check_in
        local_datetime = self._get_employee_local_datetime(
            employee,
            location_datetime,
        )
        local_date = local_datetime.date()
        # --------------------------------------------------------
        # Client-site exception bypasses location tracking.
        # --------------------------------------------------------
        if "bxi.shift.exception" in self.env:
            ShiftException = self.env[
                "bxi.shift.exception"
            ].sudo()
            client_exceptions = ShiftException.search(
                [
                    ("employee_id", "=", employee.id),
                    ("state", "=", "approved"),
                    ("date_from", "<=", local_date),
                    ("date_to", ">=", local_date),
                    ("mode", "=", "client"),
                ],
                order="id desc",
            )
            for exception in client_exceptions:
                allowed_weekdays_value = getattr(
                    exception,
                    "allowed_weekdays",
                    False,
                )
                if allowed_weekdays_value:
                    try:
                        allowed_weekdays = [
                            int(value.strip())
                            for value in allowed_weekdays_value.split(",")
                            if value.strip()
                        ]
                    except (TypeError, ValueError):
                        _logger.warning(
                            "Invalid allowed_weekdays '%s' on exception %s",
                            allowed_weekdays_value,
                            exception.name,
                        )
                        continue
                    allowed_weekdays = [
                        day for day in allowed_weekdays if 0 <= day <= 6
                    ]
                    if local_date.weekday() not in allowed_weekdays:
                        continue
                _logger.info(
                    "Client-site exception bypasses GPS validation | "
                    "employee=%s | date=%s | exception=%s",
                    employee.name,
                    local_date,
                    exception.name,
                )
                return
        # --------------------------------------------------------
        # Get employee's effective work location
        # --------------------------------------------------------
        work_location = self._get_effective_work_location(
            employee,
            local_date,
        )
        # --------------------------------------------------------
        # No location configured
        # --------------------------------------------------------
        if not work_location:
            raise UserError(
                _(
                    "No work location is configured for %s "
                    "on %s. Please contact HR to configure "
                    "the employee's work location."
                )
                % (
                    employee.name,
                    local_date.strftime("%d %B %Y"),
                )
            )
        # --------------------------------------------------------
        # HOME LOCATION
        # --------------------------------------------------------
        is_home = bool(
            getattr(
                work_location,
                "home",
                False,
            )
        )
        if is_home:
            _logger.info(
                "Home location | geofence skipped | "
                "employee=%s | date=%s | location=%s",
                employee.name,
                local_date,
                work_location.name,
            )
            return
        # --------------------------------------------------------
        # OFFICE LOCATION
        # --------------------------------------------------------
        is_office = bool(
            getattr(
                work_location,
                "office",
                False,
            )
        )
        if not is_office:
            raise UserError(
                _(
                    "The work location '%s' assigned to %s "
                    "is neither marked as Office Location nor "
                    "Home Location. Please contact HR."
                )
                % (
                    work_location.name,
                    employee.name,
                )
            )
        # --------------------------------------------------------
        # OFFICE GPS
        # --------------------------------------------------------
        office_latitude = getattr(
            work_location,
            "latitude",
            False,
        )
        office_longitude = getattr(
            work_location,
            "longitude",
            False,
        )
        radius_km = (
            getattr(
                work_location,
                "radius_km",
                2.5,
            )
            or 2.5
        )
        # --------------------------------------------------------
        # Validate office GPS configuration
        # --------------------------------------------------------
        if office_latitude in (
            None,
            False,
            "",
        ) or office_longitude in (
            None,
            False,
            "",
        ):
            raise UserError(
                _(
                    "GPS coordinates are not configured for "
                    "office location '%s'. Please contact HR."
                )
                % work_location.name
            )
        try:
            office_latitude = float(
                office_latitude
            )
            office_longitude = float(
                office_longitude
            )
            radius_km = float(
                radius_km
            )
        except (TypeError, ValueError):
            raise UserError(
                _(
                    "Invalid GPS or radius configuration for "
                    "office location '%s'."
                )
                % work_location.name
            )
        if radius_km <= 0:
            raise UserError(
                _(
                    "Allowed Radius must be greater than 0 "
                    "for office location '%s'."
                )
                % work_location.name
            )
        # --------------------------------------------------------
        # Calculate distance
        # --------------------------------------------------------
        distance_km = self._calculate_distance_km(
            office_latitude,
            office_longitude,
            latitude,
            longitude,
        )
        # --------------------------------------------------------
        # BLOCK if outside radius
        # --------------------------------------------------------
        if distance_km > radius_km:
            operation = (
                "check-in"
                if is_checkin
                else "check-out"
            )
            raise UserError(
                _(
                    "Your current location is %.2f km away "
                    "from '%s'.\n\n"
                    "Allowed radius: %.2f km.\n"
                    "Your %s is not allowed because you are "
                    "outside the permitted office area."
                )
                % (
                    distance_km,
                    work_location.name,
                    radius_km,
                    operation,
                )
            )
        # --------------------------------------------------------
        # SUCCESS
        # --------------------------------------------------------
        operation = (
            "check-in"
            if is_checkin
            else "check-out"
        )
        _logger.info(
            "Attendance GPS validated successfully | "
            "employee=%s | date=%s | operation=%s | "
            "location=%s | distance=%.2f km | allowed=%.2f km",
            employee.name,
            local_date,
            operation,
            work_location.name,
            distance_km,
            radius_km,
        )

    # ============================================================
    # ATTENDANCE STAGE

    # ============================================================

    def _evaluate_attendance_stage(self):
        for rec in self:
            if not rec.check_in or not rec.employee_id:
                continue
            tz_name = (
                rec.employee_id.tz
                or (
                    rec.employee_id.user_id
                    and rec.employee_id.user_id.tz
                )
                or self.env.user.tz
                or "Asia/Kolkata"
            )
            try:
                tz = pytz.timezone(tz_name)
            except Exception:
                tz = pytz.timezone("Asia/Kolkata")
            if rec.check_in.tzinfo:
                dt_utc = rec.check_in.astimezone(
                    pytz.utc
                )
            else:
                dt_utc = pytz.utc.localize(
                    rec.check_in
                )
            local_dt = dt_utc.astimezone(tz)
            local_date = local_dt.date()
            local_weekday = str(
                local_dt.weekday()
            )
            local_time_hours = (
                local_dt.hour
                + (local_dt.minute / 60.0)
                + (local_dt.second / 3600.0)
            )
            calendar = (
                rec.employee_id.resource_calendar_id
                or rec.employee_id.company_id.resource_calendar_id
            )
            if not calendar:
                rec.state = "approved"
                continue
            day_atts = calendar.attendance_ids.filtered(
                lambda a: a.dayofweek == local_weekday
            )
            if "date_from" in day_atts._fields:
                day_atts = day_atts.filtered(
                    lambda a:
                    (
                        not a.date_from
                        or a.date_from <= local_date
                    )
                    and
                    (
                        not a.date_to
                        or a.date_to >= local_date
                    )
                )
            if not day_atts:
                rec.state = "approved"
                continue
            sorted_atts = day_atts.sorted(
                "hour_from"
            )
            shift_start_hour = (
                sorted_atts[0].hour_from
            )
            if len(sorted_atts) > 1:
                break_start_hour = (
                    sorted_atts[0].hour_to
                )
            else:
                single_att = sorted_atts[0]
                total_duration = (
                    single_att.hour_to
                    - single_att.hour_from
                )
                break_start_hour = (
                    single_att.hour_from
                    + (total_duration / 2.0)
                )
            if local_time_hours <= (
                shift_start_hour + 0.0001
            ):
                rec.state = "approved"
            elif local_time_hours >= (
                break_start_hour - 0.0001
            ):
                rec.state = "level_2_late"
            else:
                rec.state = "level_1_late"

    # ============================================================
    # CREATE

    # ============================================================

    @api.model_create_multi
    def create(self, vals_list):
        if isinstance(vals_list, dict):
            vals_list = [vals_list]
        for vals in vals_list:
            employee_id = vals.get(
                "employee_id"
            )
            self._validate_attendance_eligibility(
                employee_id
            )
            self._validate_location_access(
                vals
            )
        records = super().create(
            vals_list
        )
        records._evaluate_attendance_stage()
        return records

    # ============================================================
    # WRITE

    # ============================================================

    def write(self, vals):
        if (
            "employee_id" in vals
            and vals.get("employee_id")
        ):
            self._validate_attendance_eligibility(
                vals.get("employee_id")
            )
        if any(
            field in vals
            for field in (
                "check_in",
                "check_out",
                "latitude",
                "longitude",
                "in_latitude",
                "in_longitude",
                "out_latitude",
                "out_longitude",
                "location",
            )
        ):
            for rec in self:
                update_vals = dict(vals)
                # Existing attendance already knows its employee.
                # Normal checkout does not usually send employee_id.
                if not update_vals.get("employee_id"):
                    update_vals["employee_id"] = (
                        rec.employee_id.id
                    )
                # ------------------------------------------------
                # CHECK-IN
                # ------------------------------------------------
                # Preserve existing check-in GPS only when the
                # check-in request does not provide coordinates.
                # ------------------------------------------------
                if (
                    "check_in" in vals
                    and "latitude" not in update_vals
                    and rec.latitude
                ):
                    update_vals["latitude"] = rec.latitude
                if (
                    "check_in" in vals
                    and "longitude" not in update_vals
                    and rec.longitude
                ):
                    update_vals["longitude"] = rec.longitude
                # ------------------------------------------------
                # CHECK-OUT
                # ------------------------------------------------
                #
                # DO NOT copy check-in latitude/longitude into
                # checkout validation.
                #
                # Checkout validation uses:
                #
                #   out_latitude
                #   out_longitude
                #
                # or the generic location payload.
                # ------------------------------------------------
                rec._validate_location_access(
                    update_vals
                )
        result = super().write(vals)
        if (
            "check_in" in vals
            or "employee_id" in vals
        ):
            self._evaluate_attendance_stage()
        return result

    # ============================================================
    # APPROVAL

    # ============================================================

    def action_set_draft(self):
        self.write(
            {
                "state": "draft",
            }
        )

    def action_level_1_late(self):
        self.write(
            {
                "state": "level_1_late",
            }
        )

    def action_level_2_late(self):
        self.write(
            {
                "state": "level_2_late",
            }
        )

    def action_approve(self):
        current_employee = (
            self._get_current_employee()
        )
        self.write(
            {
                "state": "approved",
                "approved_by_id": (
                    current_employee.id
                    if current_employee
                    else False
                ),
                "approved_datetime": fields.Datetime.now(),
            }
        )

    def action_reject(self):
        current_employee = (
            self._get_current_employee()
        )
        self.write(
            {
                "state": "rejected",
                "rejected_by_id": (
                    current_employee.id
                    if current_employee
                    else False
                ),
                "rejected_datetime": fields.Datetime.now(),
            }
        )

    # ============================================================
    # AUTO CHECKOUT + MISSED CHECKOUT LWP

    # ============================================================

    @api.model
    def _get_missed_checkout_leave_type(self):
        """Return the LWP leave type configured in Odoo."""
        LeaveType = self.env['hr.leave.type'].sudo()
        leave_type = False
        if 'code' in LeaveType._fields:
            leave_type = LeaveType.search([('code', '=', 'LWP')], limit=1)
        if not leave_type:
            leave_type = LeaveType.search([('name', '=', 'LWP')], limit=1)
        return leave_type

    @api.model
    def _get_local_date(self, attendance):
        """Return the employee-local date of the attendance check-in."""
        if not attendance.check_in:
            return fields.Date.context_today(attendance)
        employee = attendance.employee_id
        tz_name = (
            employee.user_id.tz
            or self.env.user.tz
            or 'Asia/Kolkata'
        )
        timezone = pytz.timezone(tz_name)
        check_in_utc = fields.Datetime.to_datetime(attendance.check_in)
        return pytz.UTC.localize(check_in_utc).astimezone(timezone).date()

    @api.model
    def _get_auto_checkout_datetime(self, attendance):
        """Return 11:00 PM in the employee timezone, stored as UTC."""
        employee = attendance.employee_id
        tz_name = (
            employee.user_id.tz
            or self.env.user.tz
            or 'Asia/Kolkata'
        )
        timezone = pytz.timezone(tz_name)
        local_date = self._get_local_date(attendance)
        local_checkout = timezone.localize(
            datetime.combine(local_date, datetime.min.time()).replace(
                hour=23,
                minute=0,
                second=0,
                microsecond=0,
            )
        )
        return local_checkout.astimezone(pytz.UTC).replace(tzinfo=None)

    @api.model
    def _create_missed_checkout_lwp(self, attendance):
        """Create and validate exactly one full-day LWP for the missed checkout date."""
        if not attendance.employee_id:
            return False
        # Reuse the LWP already linked to this attendance, if any.
        if 'lwp_leave_id' in attendance._fields and attendance.lwp_leave_id:
            leave = attendance.lwp_leave_id.sudo()
            for _attempt in range(2):
                if leave.state in ('validate', 'refuse', 'cancel'):
                    break
                leave.action_validate()
            return leave
        leave_type = self._get_missed_checkout_leave_type()
        if not leave_type:
            _logger.error(
                "LWP leave type was not found. Configure a leave type named/code 'LWP'. "
                "Attendance ID: %s",
                attendance.id,
            )
            return False
        leave_date = self._get_local_date(attendance)
        Leave = self.env['hr.leave'].sudo()
        # Prevent a duplicate LWP if the cron runs more than once.
        domain = [
            ('employee_id', '=', attendance.employee_id.id),
            ('holiday_status_id', '=', leave_type.id),
            ('request_date_from', '=', leave_date),
            ('request_date_to', '=', leave_date),
            ('state', 'not in', ('cancel', 'refuse')),
        ]
        leave = Leave.search(domain, limit=1)
        if not leave:
            leave = Leave.create({
                'name': 'LWP - Missed Checkout',
                'employee_id': attendance.employee_id.id,
                'holiday_status_id': leave_type.id,
                'request_date_from': leave_date,
                'request_date_to': leave_date,
            })
        # Validate the leave completely, including two-level approval setups.
        for _attempt in range(2):
            if leave.state in ('validate', 'refuse', 'cancel'):
                break
            leave.action_validate()
        if 'lwp_leave_id' in attendance._fields:
            attendance.sudo().write({'lwp_leave_id': leave.id})
        return leave

    @api.model
    def _send_missed_checkout_email(self, attendance, leave=False):
        """Send one missed-checkout email from hrsupport to the employee."""
        if 'missed_checkout_email_sent' in attendance._fields:
            if attendance.missed_checkout_email_sent:
                return False
        employee = attendance.employee_id
        recipient = employee.work_email or employee.user_id.email
        if not recipient:
            _logger.warning(
                "Cannot send missed-checkout email for attendance %s: employee %s has no email.",
                attendance.id,
                employee.display_name,
            )
            return False
        local_date = self._get_local_date(attendance)
        body_html = """
            <p>Dear %s,</p>
            <p>
                Your attendance for <strong>%s</strong> was automatically checked out
                at 11:00 PM because you did not complete the checkout manually from
                your approved/configured work location.
            </p>
            <p>
                As per the attendance policy, <strong>one LWP (Leave Without Pay)</strong>
                has been created and validated for this date.
            </p>
            <p>
                If this was due to an approved exception or a system issue, please
                contact HR Support for review.
            </p>
            <p>Regards,<br/>HR Support</p>
        """ % (employee.name, local_date.strftime('%d-%m-%Y'))
        mail = self.env['mail.mail'].sudo().create({
            'email_from': 'hrsupport@bxitech.com',
            'email_to': recipient,
            'subject': 'LWP Created - Missed Checkout - %s' % local_date.strftime('%d-%m-%Y'),
            'body_html': body_html,
            'auto_delete': True,
        })
        mail.send(raise_exception=True)
        if 'missed_checkout_email_sent' in attendance._fields:
            attendance.sudo().write({'missed_checkout_email_sent': True})
        return True

    @api.model
    def _process_missed_checkout(self, attendance):
        """Close one open attendance and apply the missed-checkout consequences."""
        if attendance.check_out:
            return False
        checkout_datetime = self._get_auto_checkout_datetime(attendance)
        # The is_auto_checkout flag intentionally bypasses GPS validation because
        # this checkout is performed by the server, not by the employee's device.
        attendance.sudo().write({
            'check_out': checkout_datetime,
            'is_auto_checkout': True,
        })
        values = {}
        if 'is_missed_checkout' in attendance._fields:
            values['is_missed_checkout'] = True
        if values:
            attendance.sudo().write(values)
        leave = self._create_missed_checkout_lwp(attendance)
        self._send_missed_checkout_email(attendance, leave)
        return True

    @api.model
    def _cron_auto_checkout(self):
        """
        Run at 11 PM local server/employee time through the configured cron.
        Every still-open attendance is auto-checked out once, one LWP is created
        for the same local date, and one email is sent to the employee.
        """
        open_attendances = self.search([
            ('check_out', '=', False),
        ])
        processed = 0
        for attendance in open_attendances:
            try:
                if self._process_missed_checkout(attendance):
                    processed += 1
            except Exception:
                _logger.exception(
                    "Failed to process missed checkout for attendance ID %s",
                    attendance.id,
                )
        _logger.info(
            "Missed-checkout cron completed. Processed %s attendance(s).",
            processed,
        )
        return True
