# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import pytz
import logging

_logger = logging.getLogger(__name__)

class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    is_auto_checkout = fields.Boolean(string='Auto Check-out', default=False)

    @api.model_create_multi
    def create(self, vals_list):
        records = super(HrAttendance, self).create(vals_list)
        for record in records:
            if record.check_in:
                record._check_late_checkin()
        return records

    def write(self, vals):
        res = super(HrAttendance, self).write(vals)
        if 'check_in' in vals:
            for record in self:
                if record.check_in:
                    record._check_late_checkin()
        return res

    def _check_late_checkin(self):
        self.ensure_one()
        if not self.check_in or not self.employee_id:
            return

        # 1. Get employee local timezone
        user_tz = pytz.timezone(self.env.user.tz or 'Asia/Kolkata')
        # Convert UTC check_in to local time
        check_in_utc = pytz.utc.localize(self.check_in) if not self.check_in.tzinfo else self.check_in
        check_in_local = check_in_utc.astimezone(user_tz)
        
        # Date value
        date_val = check_in_local.date()
        
        # Check if an auto-created late checkin leave already exists for this date to prevent duplicates
        existing_leave = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', self.employee_id.id),
            ('request_date_from', '=', date_val),
            ('name', 'like', 'Auto-created'),
            ('state', '!=', 'refuse'),
        ], limit=1)
        if existing_leave:
            return

        # 2. Get shift start hour for the weekday
        shift_start_hour = 9.0  # Default to 9:00 AM if calendar/attendance is missing
        calendar = self.employee_id.resource_calendar_id
        if calendar:
            # dayofweek in resource calendar: '0' = Monday, '6' = Sunday
            dayofweek_str = str(check_in_local.weekday())
            attendances = calendar.attendance_ids.filtered(lambda a: a.dayofweek == dayofweek_str and a.day_period == 'morning')
            if attendances:
                shift_start_hour = attendances[0].hour_from

        # 3. Check-in hour in local timezone
        check_in_hour = check_in_local.hour + (check_in_local.minute / 60.0)

        # 4. Apply rules
        # Rule A: Check-in before shift_start + 1.0 -> No action
        # Rule B: Check-in between shift_start + 1.0 and shift_start + 4.0 -> Half-day Leave with Pay
        # Rule C: Check-in after shift_start + 4.0 -> Full-day LOP (Leave Without Pay)
        
        employee_company_id = self.employee_id.company_id.id

        # Search for LOP leave type by exact leave code 'LOP': prefer company-specific, fallback to global
        unpaid_type = self.env['hr.leave.type'].sudo().search([
            ('company_id', '=', employee_company_id),
            ('code', '=', 'LOP'),
        ], limit=1)
        if not unpaid_type:
            unpaid_type = self.env['hr.leave.type'].sudo().search([
                ('company_id', '=', False),
                ('code', '=', 'LOP'),
            ], limit=1)
        if not unpaid_type:
            raise UserError(_(
                'Leave Without Pay (LOP) leave type is not configured. '
                'Please configure a leave type with code "LOP" before processing attendance.'
            ))

        paid_type = self.env['hr.leave.type'].sudo().search([
            ('company_id', '=', employee_company_id),
            '|', '|',
            ('name', 'ilike', 'casual'),
            ('name', 'ilike', 'sick'),
            ('name', 'ilike', 'with pay')
        ], limit=1)
        if not paid_type:
            paid_type = self.env['hr.leave.type'].sudo().search([
                ('company_id', '=', False),
                '|', '|',
                ('name', 'ilike', 'casual'),
                ('name', 'ilike', 'sick'),
                ('name', 'ilike', 'with pay')
            ], limit=1)
        if not paid_type:
            # Fallback to any non-unpaid type for the employee's company
            paid_type = self.env['hr.leave.type'].sudo().search([
                ('company_id', 'in', [employee_company_id, False]),
                ('name', 'not ilike', 'unpaid'),
                ('name', 'not ilike', 'without pay'),
            ], limit=1)

        # Use with_context to ensure multi-company security uses the employee's company
        leave_env = self.env['hr.leave'].sudo().with_context(
            allowed_company_ids=[employee_company_id]
        )

        if shift_start_hour + 1.0 < check_in_hour <= shift_start_hour + 4.0:
            # Create Half-day Paid Leave
            if paid_type:
                try:
                    leave_env.create({
                        'employee_id': self.employee_id.id,
                        'holiday_status_id': paid_type.id,
                        'request_date_from': date_val,
                        'request_date_to': date_val,
                        'number_of_days': 0.5,
                        'request_unit_half': True,
                        'request_date_from_period': 'am',
                        'company_id': employee_company_id,
                        'name': f'Auto-created: Half-day Leave (Late check-in at {check_in_local.strftime("%I:%M %p")} vs Shift start {self._float_to_time(shift_start_hour)})',
                    })
                except Exception as e:
                    _logger.error(f"Failed to create auto half-day leave for employee {self.employee_id.name}: {str(e)}")

        elif check_in_hour > shift_start_hour + 4.0:
            # Create Full-day LOP
            if unpaid_type:
                try:
                    leave_env.create({
                        'employee_id': self.employee_id.id,
                        'holiday_status_id': unpaid_type.id,
                        'request_date_from': date_val,
                        'request_date_to': date_val,
                        'number_of_days': 1.0,
                        'company_id': employee_company_id,
                        'name': f'Auto-created: Full-day LOP (Late check-in at {check_in_local.strftime("%I:%M %p")} vs Shift start {self._float_to_time(shift_start_hour)})',
                    })
                except Exception as e:
                    _logger.error(f"Failed to create auto LOP leave for employee {self.employee_id.name}: {str(e)}")

    def _float_to_time(self, hours):
        if not hours or hours <= 0:
            return '0:00'
        mins = round(hours * 60)
        h = mins // 60
        m = mins % 60
        return f'{h}:{m:02d}'
