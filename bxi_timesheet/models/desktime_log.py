# -*- coding: utf-8 -*-
from odoo import api, fields, models


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

    _sql_constraints = [
        (
            'unique_employee_date',
            'UNIQUE(employee_id, date)',
            'A DeskTime log entry already exists for this employee on this date.'
        ),
    ]

    @api.depends('employee_id', 'date')
    def _compute_display_name(self):
        for rec in self:
            emp = rec.employee_id.name or ''
            dt = str(rec.date) if rec.date else ''
            rec.display_name = f'{emp} / {dt}'

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
