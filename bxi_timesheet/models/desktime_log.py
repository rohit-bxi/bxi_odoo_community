# -*- coding: utf-8 -*-
from datetime import datetime, time

from pytz import timezone, utc

from odoo import _, api, fields, models


class BxiDesktimeLog(models.Model):
    """
    Stores detailed DeskTime API data per employee per day.
    Acts as audit log and source for timesheet reconciliation.
    """
    _name = 'bxi.desktime.log'
    _description = 'DeskTime Daily Employee Log'
    _order = 'date desc, employee_id'
    _rec_name = 'display_name'

    # ─────────────────────────────────────────────
    #  Identity
    # ─────────────────────────────────────────────
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        index=True,
        ondelete='cascade',
    )
    date = fields.Date(
        string='Date',
        required=True,
        index=True,
    )
    config_id = fields.Many2one(
        'bxi.desktime.config',
        string='Sync Configuration',
        ondelete='set null',
    )

    # ─────────────────────────────────────────────
    #  DeskTime Raw Info
    # ─────────────────────────────────────────────
    desktime_employee_id = fields.Integer(
        string='DeskTime Employee ID',
    )
    desktime_email = fields.Char(
        string='DeskTime Email',
    )
    desktime_name = fields.Char(
        string='DeskTime Name',
    )

    # ─────────────────────────────────────────────
    #  Attendance Times
    # ─────────────────────────────────────────────
    arrived = fields.Datetime(
        string='Arrived',
    )
    left = fields.Datetime(
        string='Left',
    )
    is_late = fields.Boolean(
        string='Late',
        default=False,
    )

    # ─────────────────────────────────────────────
    #  Shift Based Times (clamped to the employee's working schedule)
    # ─────────────────────────────────────────────
    # Not dependent on the employee's calendar: logs keep the shift times
    # computed at sync time even if the working schedule changes later.
    shift_arrived = fields.Datetime(
        string='Shift Based Arrived',
        compute='_compute_shift_times',
        store=True,
        help='Arrival time, counted from the shift start when the employee arrived earlier.',
    )
    shift_left = fields.Datetime(
        string='Shift Based Left',
        compute='_compute_shift_times',
        store=True,
        help='Leaving time, counted up to the shift end when the employee left later.',
    )
    shift_productive_hours = fields.Float(
        string='Shift Wise Production Hours',
        compute='_compute_shift_times',
        store=True,
        digits=(10, 2),
        help='Time present within the shift working hours, lunch break included.',
    )

    # ─────────────────────────────────────────────
    #  Time Metrics (in hours, converted from seconds)
    # ─────────────────────────────────────────────
    at_work_hours = fields.Float(
        string='At Work (hrs)',
        digits=(10, 2),
        help='Total time at work including offline time (atWorkTime ÷ 3600).',
    )
    online_hours = fields.Float(
        string='Online (hrs)',
        digits=(10, 2),
        help='Time tracked by DeskTime desktop app (onlineTime ÷ 3600).',
    )
    offline_hours = fields.Float(
        string='Offline (hrs)',
        digits=(10, 2),
        help='Time manually added or from mobile (offlineTime ÷ 3600).',
    )
    productive_hours = fields.Float(
        string='Productive (hrs)',
        digits=(10, 2),
        help='Time spent on productive applications (productiveTime ÷ 3600).',
    )

    # ─────────────────────────────────────────────
    #  Productivity Metrics
    # ─────────────────────────────────────────────
    productivity = fields.Float(
        string='Productivity (%)',
        digits=(5, 2),
        help='Percentage of time spent on productive applications.',
    )
    efficiency = fields.Float(
        string='Efficiency (%)',
        digits=(5, 2),
        help='Productive time as percentage of required work time.',
    )
    timezone = fields.Char(
        string='Timezone',
    )
    desktime_hours = fields.Float(
        string='DeskTime Tracked (hrs)',
        digits=(10, 2),
    )
    unproductive_hours = fields.Float(
        string='Unproductive (hrs)',
        digits=(10, 2),
    )
    neutral_hours = fields.Float(
        string='Neutral (hrs)',
        digits=(10, 2),
    )
    active_level = fields.Float(
        string='Active Level (%)',
        digits=(5, 2),
    )
    is_absent = fields.Boolean(
        string='Absent',
        default=False,
    )
    suspicious_count = fields.Integer(
        string='Suspicious Count',
        default=0,
    )
    raw_json = fields.Text(
        string='Raw API JSON',
    )

    # ─────────────────────────────────────────────
    #  Linked Timesheet
    # ─────────────────────────────────────────────
    timesheet_id = fields.Many2one(
        'account.analytic.line',
        string='Timesheet Entry',
        ondelete='set null',
        copy=False,
    )
    timesheet_unit_amount = fields.Float(
        string='Timesheet Hours',
        related='timesheet_id.unit_amount',
        readonly=True,
    )

    # ─────────────────────────────────────────────
    #  Computed
    # ─────────────────────────────────────────────
    display_name = fields.Char(
        compute='_compute_display_name',
        store=True,
    )
    department_id = fields.Many2one(
        related='employee_id.department_id',
        string='Department',
        store=True,
    )

    _unique_employee_date = models.Constraint(
        'UNIQUE(employee_id, date)',
        'A DeskTime log entry already exists for this employee on this date.',
    )

    @api.depends('employee_id', 'date')
    def _compute_display_name(self):
        for rec in self:
            emp = rec.employee_id.name or ''
            dt = str(rec.date) if rec.date else ''
            rec.display_name = f'{emp} / {dt}'

    @api.depends('arrived', 'left', 'date', 'employee_id')
    def _compute_shift_times(self):
        for rec in self:
            rec.shift_arrived = False
            rec.shift_left = False
            rec.shift_productive_hours = 0.0

            intervals = rec._get_shift_intervals()
            if not intervals or not rec.arrived:
                continue
            shift_start = intervals[0][0]
            shift_end = intervals[-1][1]
            arrived = utc.localize(rec.arrived)
            left = utc.localize(rec.left) if rec.left else False
            # Present only outside the shift window: nothing to count
            if arrived >= shift_end or (left and left <= shift_start):
                continue

            shift_arrived = max(arrived, shift_start)
            rec.shift_arrived = shift_arrived.astimezone(utc).replace(tzinfo=None)
            if not left:
                continue
            shift_left = min(left, shift_end)
            rec.shift_left = shift_left.astimezone(utc).replace(tzinfo=None)
            # Lunch break is counted: the intervals include the schedule's break lines
            seconds = sum(
                max((min(shift_left, stop) - max(shift_arrived, start)).total_seconds(), 0)
                for start, stop, _attendance in intervals
            )
            rec.shift_productive_hours = round(seconds / 3600.0, 4)

    def _get_shift_intervals(self):
        """Working intervals of the employee's schedule on the log date, as a sorted list of
        (start, stop, attendances) with timezone-aware datetimes. Lunch break lines are included,
        so the break between the intervals is counted in the shift wise hours."""
        self.ensure_one()
        calendar = self.employee_id.resource_calendar_id
        if not calendar or calendar.flexible_hours or not self.date:
            return []
        tz = timezone(calendar.tz or 'UTC')
        day_start = tz.localize(datetime.combine(self.date, time.min))
        day_end = tz.localize(datetime.combine(self.date, time.max))
        work = calendar._attendance_intervals_batch(day_start, day_end, tz=tz)[False]
        lunch = calendar._attendance_intervals_batch(day_start, day_end, tz=tz, lunch=True)[False]
        # Union merges overlapping lines, so no time is counted twice
        return sorted(work | lunch, key=lambda interval: interval[0])

    def action_recompute_shift_times(self):
        """Recalculate shift based arrived/left and shift wise hours with the employees'
        current working schedules (logs otherwise keep the values from sync time)."""
        self.check_access('write')
        fnames = ['shift_arrived', 'shift_left', 'shift_productive_hours']
        for fname in fnames:
            self.env.add_to_compute(self._fields[fname], self)
        self._recompute_recordset(fnames)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Shift Times Recalculated'),
                'message': _('%s log(s) recalculated with the current working schedules.') % len(self),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_view_timesheet(self):
        """Open the linked timesheet entry."""
        self.ensure_one()
        if not self.timesheet_id:
            return
        return {
            'type': 'ir.actions.act_window',
            'name': 'Timesheet Entry',
            'res_model': 'account.analytic.line',
            'res_id': self.timesheet_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
