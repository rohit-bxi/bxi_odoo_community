# -*- coding: utf-8 -*-
import logging
import requests
from datetime import datetime, date, time

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DESKTIME_API_URL = "https://desktime.com/api/v2/json/employees"


class BxiDesktimeConfig(models.Model):
    """
    Singleton-style configuration record for DeskTime API integration.
    Only one active config record is expected per company.
    """
    _name = 'bxi.desktime.config'
    _description = 'DeskTime API Configuration'
    _inherit = ['mail.thread']
    _rec_name = 'name'

    name = fields.Char(
        string='Configuration Name',
        default='DeskTime Integration',
        required=True,
    )
    api_key = fields.Char(
        string='API Key',
        required=True,
        tracking=True,
        help='Your DeskTime API key (account-level key).',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        tracking=True,
    )
    default_project_id = fields.Many2one(
        'project.project',
        string='Default Timesheet Project',
        help='Timesheet entries created from DeskTime data will be linked to this project. '
             'If not set, timesheets will be created without a project.',
        tracking=True,
        options="{'no_create': True, 'no_open': True, 'no_edit': True}",
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    last_sync_date = fields.Date(
        string='Last Sync Date',
        readonly=True,
    )
    last_sync_status = fields.Text(
        string='Last Sync Status',
        readonly=True,
    )
    last_sync_datetime = fields.Datetime(
        string='Last Sync At',
        readonly=True,
    )

    # ─────────────────────────────────────────────
    #  Scheduled Action Entry Point
    # ─────────────────────────────────────────────
    @api.model
    def _cron_sync_desktime(self):
        """Called by the daily scheduled action at 23:30."""
        configs = self.search([('active', '=', True)])
        if not configs:
            _logger.warning('BXI DeskTime: No active configuration found. Skipping sync.')
            return
        for config in configs:
            try:
                config._sync_for_date(date.today())
            except Exception as e:
                _logger.error('BXI DeskTime: Sync failed for config %s: %s', config.name, str(e))
                config.write({
                    'last_sync_status': f'ERROR: {str(e)}',
                    'last_sync_datetime': fields.Datetime.now(),
                })

    # ─────────────────────────────────────────────
    #  Manual Trigger
    # ─────────────────────────────────────────────
    def action_sync_now(self):
        """Button action to manually trigger sync for today."""
        self.ensure_one()
        self._sync_for_date(date.today())
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('DeskTime Sync'),
                'message': _('Sync completed for %s. Check the Sync Logs for details.') % (
                    fields.Date.today()
                ),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_sync_for_date(self):
        """Open a wizard to pick a custom date for sync — calls _sync_for_date."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sync DeskTime for Date'),
            'res_model': 'bxi.desktime.sync.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_config_id': self.id},
        }

    # ─────────────────────────────────────────────
    #  Core Sync Logic
    # ─────────────────────────────────────────────
    def _sync_for_date(self, sync_date):
        """
        Fetch DeskTime data for `sync_date` and create/update:
        - bxi.desktime.log records
        - account.analytic.line (timesheet) records
        """
        self.ensure_one()

        if not self.api_key:
            raise UserError(_('DeskTime API key is not configured.'))

        date_str = sync_date.strftime('%Y-%m-%d') if isinstance(sync_date, date) else sync_date

        # ── 1. Fetch data from DeskTime ──────────────────────────────────
        url = DESKTIME_API_URL
        params = {
            'apiKey': self.api_key,
            'date': date_str,
            'period': 'day',
        }
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            error_msg = f'DeskTime API request failed: {str(e)}'
            _logger.error('BXI DeskTime: %s', error_msg)
            self.write({
                'last_sync_status': f'ERROR: {error_msg}',
                'last_sync_datetime': fields.Datetime.now(),
            })
            raise UserError(_(error_msg))

        employees_by_date = data.get('employees', {})
        if not employees_by_date:
            _logger.info('BXI DeskTime: No employee data returned for %s', date_str)
            self.write({
                'last_sync_date': sync_date,
                'last_sync_status': f'No data returned for {date_str}.',
                'last_sync_datetime': fields.Datetime.now(),
            })
            return

        # ── 2. Process each date block returned (API may return multiple dates) ──
        created_count = 0
        updated_count = 0
        skipped_count = 0

        for api_date_key, employees_dict in employees_by_date.items():
            # Parse date from API response key (format: "Y-m-d")
            try:
                record_date = datetime.strptime(api_date_key, '%Y-%m-%d').date()
            except ValueError:
                _logger.warning('BXI DeskTime: Could not parse date key "%s", skipping.', api_date_key)
                continue

            for emp_id_str, emp_data in employees_dict.items():
                result = self._process_employee_data(record_date, emp_data)
                if result == 'created':
                    created_count += 1
                elif result == 'updated':
                    updated_count += 1
                else:
                    skipped_count += 1

        status_msg = (
            f'Sync for {date_str} complete. '
            f'Created: {created_count}, Updated: {updated_count}, Skipped (no match): {skipped_count}.'
        )
        _logger.info('BXI DeskTime: %s', status_msg)
        self.write({
            'last_sync_date': sync_date,
            'last_sync_status': status_msg,
            'last_sync_datetime': fields.Datetime.now(),
        })

    def _process_employee_data(self, record_date, emp_data):
        """
        Create or update bxi.desktime.log and account.analytic.line
        for a single employee record from the DeskTime API.
        Returns 'created', 'updated', or 'skipped'.
        """
        email = emp_data.get('email', '').strip().lower()
        desktime_emp_id = emp_data.get('id')
        emp_name = emp_data.get('name', '')

        # ── Match Odoo employee by work_email ──────────────────────────
        odoo_employee = self.env['hr.employee'].search(
            [('work_email', '=ilike', email)],
            limit=1
        )
        if not odoo_employee:
            _logger.debug(
                'BXI DeskTime: No Odoo employee found for email "%s" (DeskTime: %s). Skipping.',
                email, emp_name
            )
            return 'skipped'

        # ── Time calculations (seconds → hours) ────────────────────────
        at_work_seconds = emp_data.get('atWorkTime') or 0
        online_seconds = emp_data.get('onlineTime') or 0
        offline_seconds = emp_data.get('offlineTime') or 0
        productive_seconds = emp_data.get('productiveTime') or 0
        desktime_seconds = emp_data.get('desktimeTime') or 0
        unproductive_seconds = emp_data.get('unproductiveTime') or 0
        neutral_seconds = emp_data.get('neutralTime') or 0

        at_work_hours = round(at_work_seconds / 3600.0, 4)
        online_hours = round(online_seconds / 3600.0, 4)
        offline_hours = round(offline_seconds / 3600.0, 4)
        productive_hours = round(productive_seconds / 3600.0, 4)
        desktime_hours = round(desktime_seconds / 3600.0, 4)
        unproductive_hours = round(unproductive_seconds / 3600.0, 4)
        neutral_hours = round(neutral_seconds / 3600.0, 4)

        productivity = emp_data.get('productivity') or 0.0
        efficiency = emp_data.get('efficiency') or 0.0
        is_late = emp_data.get('late', False)
        active_level = emp_data.get('activeLevel') or emp_data.get('activityLevel') or 0.0
        is_absent = emp_data.get('absent', False)
        suspicious_count = emp_data.get('suspiciousCount') or 0

        # ── Parse arrived / left times (convert local timezone to UTC) ──
        import pytz
        arrived_dt = False
        left_dt = False
        arrived_raw = emp_data.get('arrived')
        left_raw = emp_data.get('left')
        timezone_str = emp_data.get('timezone') or 'Asia/Kolkata'
        try:
            tz = pytz.timezone(timezone_str)
        except Exception:
            tz = pytz.timezone('Asia/Kolkata')

        if arrived_raw and arrived_raw is not False:
            try:
                local_dt = datetime.strptime(str(arrived_raw), '%Y-%m-%d %H:%M:%S')
                local_dt = tz.localize(local_dt)
                arrived_dt = local_dt.astimezone(pytz.utc).replace(tzinfo=None)
            except (ValueError, TypeError):
                pass
        if left_raw and left_raw is not False:
            try:
                local_dt = datetime.strptime(str(left_raw), '%Y-%m-%d %H:%M:%S')
                local_dt = tz.localize(local_dt)
                left_dt = local_dt.astimezone(pytz.utc).replace(tzinfo=None)
            except (ValueError, TypeError):
                pass

        # ── Find or create bxi.desktime.log ───────────────────────────
        existing_log = self.env['bxi.desktime.log'].search([
            ('employee_id', '=', odoo_employee.id),
            ('date', '=', record_date),
        ], limit=1)

        import json
        log_vals = {
            'employee_id': odoo_employee.id,
            'date': record_date,
            'desktime_employee_id': desktime_emp_id,
            'desktime_email': email,
            'desktime_name': emp_name,
            'arrived': arrived_dt,
            'left': left_dt,
            'at_work_hours': at_work_hours,
            'online_hours': online_hours,
            'offline_hours': offline_hours,
            'productive_hours': productive_hours,
            'productivity': productivity,
            'efficiency': efficiency,
            'is_late': is_late,
            'config_id': self.id,
            'timezone': timezone_str,
            'desktime_hours': desktime_hours,
            'unproductive_hours': unproductive_hours,
            'neutral_hours': neutral_hours,
            'active_level': active_level,
            'is_absent': is_absent,
            'suspicious_count': suspicious_count,
            'raw_json': json.dumps(emp_data, indent=4) if emp_data else '{}',
        }

        action = 'created'
        if existing_log:
            existing_log.write(log_vals)
            action = 'updated'
            log_record = existing_log
        else:
            log_record = self.env['bxi.desktime.log'].create(log_vals)

        # ── Auto Checkout Odoo Attendance from DeskTime ───────────────
        if 'hr.attendance' in self.env and left_dt:
            dt_min = datetime.combine(record_date, time.min)
            dt_max = datetime.combine(record_date, time.max)
            
            open_attendance = self.env['hr.attendance'].sudo().search([
                ('employee_id', '=', odoo_employee.id),
                ('check_in', '>=', dt_min),
                ('check_in', '<=', dt_max),
                ('check_out', '=', False)
            ], limit=1)
            
            if open_attendance:
                # Check if is_auto_checkout is defined on model before writing
                write_vals = {'check_out': left_dt}
                if 'is_auto_checkout' in open_attendance._fields:
                    write_vals['is_auto_checkout'] = True
                open_attendance.write(write_vals)

        # Timesheet creation/updates disabled per requirement:
        # "while syncing the logs from the desktime api from schedule or manual on logs will create in sync log not the timesheet"
        pass

        return action
