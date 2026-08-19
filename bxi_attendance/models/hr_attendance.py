# -*- coding: utf-8 -*-
import pytz
from odoo import models, fields, api, _


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    state = fields.Selection([
        ('draft', 'Draft'),
        ('level_1_late', 'Level 1 Late'),
        ('level_2_late', 'Level 2 Late'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Stage', default='draft', copy=False, index=True)

    is_auto_checkout = fields.Boolean(string='Auto Check-out', default=False)

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

