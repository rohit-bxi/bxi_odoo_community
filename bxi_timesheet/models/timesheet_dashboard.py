# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import datetime, timedelta, date
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class BxiTimesheetDashboard(models.AbstractModel):
    """
    Transient/helper model to serve data for the Weekly Timesheet Dashboard.
    Requires no DB table.
    """
    _name = 'bxi.timesheet.dashboard'
    _description = 'Weekly Timesheet Dashboard API'

    @api.model
    def get_dashboard_data(self, employee_id=None, start_date_str=None, filter_type='own'):
        """
        Fetch weekly timesheet records, projects, tasks, checkin/checkout times,
        and team list/summary. Returns structured dict for OWL dashboard.
        """
        user = self.env.user
        # Multi-company: IDs of all companies the current user is allowed to access
        allowed_company_ids = self.env.companies.ids

        # 1. Resolve employee and permissions
        current_employee = self.env['hr.employee'].search([
            ('user_id', '=', user.id),
            ('company_id', 'in', allowed_company_ids),
        ], limit=1)

        is_admin = (
            user.has_group('base.group_system') or
            user.has_group('base.group_erp_manager') or
            user.has_group('hr_timesheet.group_timesheet_manager') or
            user.has_group('hr.group_hr_manager')
        )
        is_hr = (
            user.has_group('hr.group_hr_user') or
            user.has_group('hr_timesheet.group_timesheet_manager')
        )
        is_approver = user.has_group('hr_timesheet.group_hr_timesheet_approver')

        # Determine manager status (has direct reports within allowed companies)
        is_manager = False
        subordinates = self.env['hr.employee']
        if current_employee:
            subordinates = self.env['hr.employee'].search([
                ('parent_id', '=', current_employee.id),
                ('company_id', 'in', allowed_company_ids),
            ])
            is_manager = len(subordinates) > 0

        # Build list of allowed employees — always scoped to user's companies
        if is_admin or is_hr:
            allowed_employees = self.env['hr.employee'].search([
                ('active', '=', True),
                ('company_id', 'in', allowed_company_ids),
            ])
        elif is_approver or is_manager:
            allowed_employees = current_employee + subordinates
        elif current_employee:
            allowed_employees = current_employee
        else:
            allowed_employees = self.env['hr.employee']

        # Determine target employee
        target_employee = current_employee
        if employee_id:
            emp = self.env['hr.employee'].browse(int(employee_id))
            if emp in allowed_employees:
                target_employee = emp
            else:
                target_employee = current_employee

        # 2. Setup weekly date range
        current_week_start = self._get_current_week_start()
        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            except ValueError:
                start_date = current_week_start
        else:
            start_date = current_week_start

        end_date = start_date + timedelta(days=6)
        is_past_week = start_date < current_week_start

        # 3. Retrieve projects and tasks scoped to allowed companies
        projects = self.env['project.project'].search_read([
            ('active', '=', True),
            ('company_id', 'in', allowed_company_ids),
        ], ['id', 'name'])
        project_ids = [p['id'] for p in projects]
        tasks = self.env['project.task'].search_read([
            ('project_id', 'in', project_ids),
            ('active', '=', True),
        ], ['id', 'name', 'project_id'])

        # 4. Fetch attendances and desktime logs for target employee
        import pytz
        timezone_str = self.env.user.tz or 'Asia/Kolkata'
        try:
            user_tz = pytz.timezone(timezone_str)
        except Exception:
            user_tz = pytz.timezone('Asia/Kolkata')

        has_attendance = 'hr.attendance' in self.env
        attendances = self.env['hr.attendance']
        if target_employee and has_attendance:
            attendances = self.env['hr.attendance'].search([
                ('employee_id', '=', target_employee.id),
                ('employee_id.company_id', 'in', allowed_company_ids),
                ('check_in', '>=', datetime.combine(start_date, datetime.min.time()) - timedelta(days=1)),
                ('check_in', '<=', datetime.combine(end_date, datetime.max.time()) + timedelta(days=1)),
            ])

        dt_logs = self.env['bxi.desktime.log']
        if target_employee:
            dt_logs = self.env['bxi.desktime.log'].sudo().search([
                ('employee_id', '=', target_employee.id),
                ('employee_id.company_id', 'in', allowed_company_ids),
                ('date', '>=', start_date),
                ('date', '<=', end_date),
            ])

        calendar = target_employee.resource_calendar_id if target_employee else False
        shift_name = calendar.name if calendar else _('No Shift')

        # 5. Retrieve grid lines for target employee to compute daily totals first
        grid_lines = []
        draft_count = 0
        submitted_count = 0
        approved_count = 0
        refused_count = 0

        grouped = {}
        if target_employee:
            domain = [
                ('employee_id', '=', target_employee.id),
                ('company_id', 'in', allowed_company_ids),
                ('date', '>=', start_date),
                ('date', '<=', end_date),
            ]
            ts_lines = self.env['account.analytic.line'].search(domain)

            draft_count = len(ts_lines.filtered(lambda l: l.state == 'draft'))
            submitted_count = len(ts_lines.filtered(lambda l: l.state == 'submitted'))
            approved_count = len(ts_lines.filtered(lambda l: l.state == 'approved'))
            refused_count = len(ts_lines.filtered(lambda l: l.state == 'refused'))

            # Group timesheets by project, task & description
            for line in ts_lines:
                proj_id = line.project_id.id or 0
                proj_name = line.project_id.name or _('No Project')
                tsk_id = line.task_id.id or 0
                tsk_name = line.task_id.name or _('No Task')
                desc = line.name or ''

                key = (proj_id, tsk_id, desc)
                if key not in grouped:
                    grouped[key] = {
                        'project_id': proj_id,
                        'project_name': proj_name,
                        'task_id': tsk_id,
                        'task_name': tsk_name,
                        'description': desc,
                        'days': [0.0] * 7,
                        'states': ['draft'] * 7
                    }

                day_idx = (line.date - start_date).days
                if 0 <= day_idx < 7:
                    grouped[key]['days'][day_idx] += line.unit_amount
                    grouped[key]['states'][day_idx] = line.state

        # Compute daily totals list
        daily_totals_raw = [0.0] * 7
        for key, val in grouped.items():
            for i in range(7):
                daily_totals_raw[i] += val['days'][i]

        # Dates array for columns (with direct properties and daily totals)
        dates_list = []
        for i in range(7):
            d = start_date + timedelta(days=i)
            
            # Attendance Check-in / Check-out
            day_attendances = []
            for att in attendances:
                if att.check_in:
                    local_in = pytz.utc.localize(att.check_in).astimezone(user_tz)
                    if local_in.date() == d:
                        day_attendances.append(att)

            check_in_time = ''
            check_out_time = ''

            if day_attendances:
                earliest_att = min(day_attendances, key=lambda a: a.check_in)
                if earliest_att.check_in:
                    check_in_time = self._format_time_12h(earliest_att.check_in, user_tz)

                atts_with_checkout = [a for a in day_attendances if a.check_out]
                if atts_with_checkout:
                    latest_att = max(atts_with_checkout, key=lambda a: a.check_out)
                    check_out_time = self._format_time_12h(latest_att.check_out, user_tz)
                else:
                    dt_log = dt_logs.filtered(lambda l: l.date == d)
                    if dt_log and dt_log[0].left:
                        check_out_time = self._format_time_12h(dt_log[0].left, user_tz)
            else:
                dt_log = dt_logs.filtered(lambda l: l.date == d)
                if dt_log:
                    if dt_log[0].arrived:
                        check_in_time = self._format_time_12h(dt_log[0].arrived, user_tz)
                    if dt_log[0].left:
                        check_out_time = self._format_time_12h(dt_log[0].left, user_tz)

            # DeskTime Productive Hours
            dt_log = dt_logs.filtered(lambda l: l.date == d)
            prod_h = dt_log[0].productive_hours if (dt_log and dt_log[0].productive_hours) else 0.0
            prod_hours_str = self._float_to_time(prod_h)

            # Shift Hours
            if calendar:
                day_str = str(d.weekday())
                day_atts = calendar.attendance_ids.filtered(lambda a: a.dayofweek == day_str)
                if 'date_from' in day_atts._fields:
                    day_atts = day_atts.filtered(lambda a: (not a.date_from or a.date_from <= d) and (not a.date_to or a.date_to >= d))
                day_shift_h = sum(a.hour_to - a.hour_from for a in day_atts)
            else:
                day_shift_h = 0.0

            if day_shift_h > 0:
                shift_hours_str = f"{shift_name} ({self._float_to_time(day_shift_h)})"
            else:
                shift_hours_str = "Off (0:00)"

            dates_list.append({
                'date_str': d.strftime('%Y-%m-%d'),
                'day_name': d.strftime('%A'),
                'day_date': f"{d.month}/{d.day}/{d.year}",
                'is_today': d == date.today(),
                'check_in': check_in_time or '-',
                'check_out': check_out_time or '-',
                'prod_hours': prod_hours_str,
                'shift_hours': shift_hours_str,
                'prod_hours_raw': prod_h,
                'shift_hours_raw': day_shift_h,
                'daily_total': self._float_to_time(daily_totals_raw[i]),
            })

        # Calculate totals
        total_prod_raw = sum(x['prod_hours_raw'] for x in dates_list)
        total_prod_str = self._float_to_time(total_prod_raw)

        total_shift_raw = sum(x['shift_hours_raw'] for x in dates_list)
        total_shift_str = self._float_to_time(total_shift_raw)

        # Build grid lines list with days_data structured list
        for idx, (key, val) in enumerate(grouped.items()):
            days_str = [self._float_to_time(h) for h in val['days']]
            row_total = sum(val['days'])
            row_total_str = self._float_to_time(row_total)

            days_data = []
            for i, d_dict in enumerate(dates_list):
                days_data.append({
                    'hours': days_str[i],
                    'hours_raw': val['days'][i],
                    'date_str': d_dict['date_str'],
                    'is_today': d_dict['is_today'],
                    'state': val['states'][i]
                })

            grid_lines.append({
                'index': idx,
                'project_id': val['project_id'],
                'project_name': val['project_name'],
                'task_id': val['task_id'],
                'task_name': val['task_name'],
                'description': val['description'],
                'days_data': days_data,
                'total': row_total_str,
                'total_raw': row_total,
            })

        # 6. Generate team summary (ONLY count Approved timesheets, include Check-in/Check-out per employee)
        team_summary = []
        if filter_type == 'team' and (is_manager or is_hr or is_admin):
            # For a manager: show only direct reports; for HR/admin: all employees in allowed companies
            if is_admin or is_hr:
                team_members = allowed_employees
            else:
                # Manager: their own record + subordinates in allowed companies
                team_members = current_employee + subordinates if current_employee else subordinates

            has_attendance = 'hr.attendance' in self.env
            all_attendances = self.env['hr.attendance']
            if has_attendance:
                all_attendances = self.env['hr.attendance'].search([
                    ('employee_id', 'in', team_members.ids),
                    ('employee_id.company_id', 'in', allowed_company_ids),
                    ('check_in', '>=', datetime.combine(start_date, datetime.min.time()) - timedelta(days=1)),
                    ('check_in', '<=', datetime.combine(end_date, datetime.max.time()) + timedelta(days=1)),
                ])

            all_dt_logs = self.env['bxi.desktime.log'].sudo().search([
                ('employee_id', 'in', team_members.ids),
                ('employee_id.company_id', 'in', allowed_company_ids),
                ('date', '>=', start_date),
                ('date', '<=', end_date),
            ])

            # Fetch ONLY approved timesheet lines — scoped to company
            domain = [
                ('employee_id', 'in', team_members.ids),
                ('company_id', 'in', allowed_company_ids),
                ('date', '>=', start_date),
                ('date', '<=', end_date),
                ('state', '=', 'approved'),
            ]
            lines = self.env['account.analytic.line'].search(domain)

            for member in team_members:
                member_lines = lines.filtered(lambda l: l.employee_id.id == member.id)
                day_hours = [0.0] * 7
                for line in member_lines:
                    day_idx = (line.date - start_date).days
                    if 0 <= day_idx < 7:
                        day_hours[day_idx] += line.unit_amount

                day_hours_str = [self._float_to_time(h) for h in day_hours]
                total_hours = sum(day_hours)
                total_hours_str = self._float_to_time(total_hours)

                # Fetch checkin / checkout times for member
                member_atts = all_attendances.filtered(lambda a: a.employee_id.id == member.id)
                member_dt_logs = all_dt_logs.filtered(lambda l: l.employee_id.id == member.id)

                day_data = []
                for idx, d_dict in enumerate(dates_list):
                    d_val = datetime.strptime(d_dict['date_str'], '%Y-%m-%d').date()

                    day_attendances = []
                    for att in member_atts:
                        if att.check_in:
                            local_in = pytz.utc.localize(att.check_in).astimezone(user_tz)
                            if local_in.date() == d_val:
                                day_attendances.append(att)

                    check_in_time = ''
                    check_out_time = ''

                    if day_attendances:
                        earliest_att = min(day_attendances, key=lambda a: a.check_in)
                        if earliest_att.check_in:
                            check_in_time = self._format_time_12h(earliest_att.check_in, user_tz)

                        atts_with_checkout = [a for a in day_attendances if a.check_out]
                        if atts_with_checkout:
                            latest_att = max(atts_with_checkout, key=lambda a: a.check_out)
                            check_out_time = self._format_time_12h(latest_att.check_out, user_tz)
                        else:
                            dt_log = member_dt_logs.filtered(lambda l: l.date == d_val)
                            if dt_log and dt_log[0].left:
                                check_out_time = self._format_time_12h(dt_log[0].left, user_tz)
                    else:
                        dt_log = member_dt_logs.filtered(lambda l: l.date == d_val)
                        if dt_log:
                            if dt_log[0].arrived:
                                check_in_time = self._format_time_12h(dt_log[0].arrived, user_tz)
                            if dt_log[0].left:
                                check_out_time = self._format_time_12h(dt_log[0].left, user_tz)

                    day_data.append({
                        'date_str': d_dict['date_str'],
                        'check_in': check_in_time or '-',
                        'check_out': check_out_time or '-',
                        'hours': day_hours_str[idx],
                        'is_today': d_dict['is_today']
                    })

                team_summary.append({
                    'employee_id': member.id,
                    'employee_name': member.name,
                    'day_hours': day_hours_str,
                    'total_hours': total_hours_str,
                    'total_hours_raw': total_hours,
                    'day_data': day_data,
                })

        overall_total = sum(daily_totals_raw)
        overall_total_str = self._float_to_time(overall_total)

        employee_options = [{
            'id': emp.id,
            'name': emp.name,
            'is_current': emp.id == current_employee.id if current_employee else False
        } for emp in allowed_employees]

        # Check if the logged-in user is a manager of the target employee
        is_target_employee_manager = False
        if current_employee and target_employee:
            is_target_employee_manager = target_employee.parent_id.id == current_employee.id

        return {
            'employee_id': target_employee.id if target_employee else False,
            'employee_name': target_employee.name if target_employee else '',
            'is_manager': is_manager,
            'is_hr': is_hr,
            'is_admin': is_admin,
            'is_target_employee_manager': is_target_employee_manager,
            'is_past_week': is_past_week,
            'dates': dates_list,
            'grid_lines': grid_lines,
            'overall_total': overall_total_str,
            'overall_total_raw': overall_total,
            'employee_options': employee_options,
            'team_summary': team_summary,
            'projects': projects,
            'tasks': tasks,
            'filter_type': filter_type,
            'start_date_str': start_date.strftime('%Y-%m-%d'),
            'end_date_str': end_date.strftime('%Y-%m-%d'),
            'draft_count': draft_count,
            'submitted_count': submitted_count,
            'approved_count': approved_count,
            'refused_count': refused_count,
            'total_prod_str': total_prod_str,
            'total_shift_str': total_shift_str,
        }

    def _format_time_12h(self, dt, tz):
        """Format datetime to 12-hour format with AM/PM (e.g. 9:58 AM)."""
        if not dt:
            return ''
        import pytz
        dt_utc = pytz.utc.localize(dt) if not dt.tzinfo else dt
        local_dt = dt_utc.astimezone(tz)
        formatted = local_dt.strftime('%I:%M %p')
        if formatted.startswith('0'):
            formatted = formatted[1:]
        return formatted

    def _get_current_week_start(self):
        """Find the preceding Sunday."""
        today = date.today()
        offset = (today.weekday() + 1) % 7
        return today - timedelta(days=offset)

    def _float_to_time(self, hours):
        """Format 2.5 hours to "2:30"."""
        if not hours or hours <= 0:
            return '0:00'
        mins = round(hours * 60)
        h = mins // 60
        m = mins % 60
        return f'{h}:{m:02d}'

    @api.model
    def save_timesheet_hours(self, employee_id, date_str, project_id, task_id, amount_str, description=None):
        """
        Add or update account.analytic.line records.
        """
        user = self.env.user
        allowed_company_ids = self.env.companies.ids
        current_employee = self.env['hr.employee'].search([
            ('user_id', '=', user.id),
            ('company_id', 'in', allowed_company_ids),
        ], limit=1)

        is_admin = user.has_group('base.group_system') or user.has_group('base.group_erp_manager') or user.has_group('hr_timesheet.group_timesheet_manager') or user.has_group('hr.group_hr_manager')
        is_hr = user.has_group('hr.group_hr_user') or user.has_group('hr_timesheet.group_timesheet_manager')
        is_approver = user.has_group('hr_timesheet.group_hr_timesheet_approver')

        subordinates = self.env['hr.employee']
        if current_employee:
            subordinates = self.env['hr.employee'].search([
                ('parent_id', '=', current_employee.id),
                ('company_id', 'in', allowed_company_ids),
            ])

        # allowed_employee_ids — always scoped to user's companies
        allowed_employee_ids = []
        if is_admin or is_hr:
            allowed_employee_ids = self.env['hr.employee'].search([
                ('active', '=', True),
                ('company_id', 'in', allowed_company_ids),
            ]).ids
        else:
            allowed_employee_ids = [current_employee.id] if current_employee else []
            allowed_employee_ids += subordinates.ids

        target_emp_id = int(employee_id)
        if target_emp_id not in allowed_employee_ids:
            raise UserError(_('You are not authorized to edit timesheets for this employee.'))

        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        current_week_start = self._get_current_week_start()
        is_manager = is_approver or (current_employee and target_emp_id in subordinates.ids)

        # Past week lock check
        if target_date < current_week_start:
            raise UserError(_("Once a week is crossed, timesheets for the previous week cannot be modified or submitted."))

        # Parse hours
        amount = 0.0
        if amount_str:
            amount_str = str(amount_str).strip()
            if ':' in amount_str:
                parts = amount_str.split(':')
                try:
                    h = int(parts[0])
                    m = int(parts[1]) if len(parts) > 1 else 0
                    amount = h + (m / 60.0)
                except ValueError:
                    amount = 0.0
            else:
                try:
                    amount = float(amount_str)
                except ValueError:
                    amount = 0.0

        if amount > 9.0:
            raise UserError(_("You cannot log more than 9 hours for a single day."))

        proj_id = int(project_id) if project_id else False
        tsk_id = int(task_id) if task_id else False

        domain = [
            ('employee_id', '=', target_emp_id),
            ('date', '=', target_date),
            ('project_id', '=', proj_id),
            ('task_id', '=', tsk_id),
        ]
        if description is not None:
            domain.append(('name', '=', description))

        existing_line = self.env['account.analytic.line'].search(domain, limit=1)

        if existing_line:
            # Block edits on approved timesheets for employees
            if existing_line.state == 'approved':
                if not (is_admin or is_hr or is_manager):
                    raise UserError(_("You cannot edit a timesheet that has already been approved."))

            if amount <= 0.0:
                existing_line.unlink()
            else:
                write_vals = {'unit_amount': amount}
                if description is not None:
                    write_vals['name'] = description
                existing_line.write(write_vals)
        else:
            if amount > 0.0:
                task_name = self.env['project.task'].browse(tsk_id).name if tsk_id else ''
                proj_name = self.env['project.project'].browse(proj_id).name if proj_id else ''
                # Use the target employee's company for the timesheet line
                target_emp = self.env['hr.employee'].browse(target_emp_id)
                emp_company_id = target_emp.company_id.id or self.env.company.id

                line_name = description if description else (f"{proj_name} / {task_name}" if proj_name and task_name else "Logged via Dashboard")

                vals = {
                    'employee_id': target_emp_id,
                    'date': target_date,
                    'project_id': proj_id,
                    'task_id': tsk_id,
                    'unit_amount': amount,
                    'name': line_name,
                    'company_id': emp_company_id,
                    'state': 'draft',
                }
                self.env['account.analytic.line'].with_context(
                    allowed_company_ids=[emp_company_id]
                ).create(vals)

        return True

    @api.model
    def submit_weekly_timesheet(self, employee_id, start_date_str):
        """Submit all draft timesheets for this employee and week."""
        user = self.env.user
        allowed_company_ids = self.env.companies.ids
        current_employee = self.env['hr.employee'].search([
            ('user_id', '=', user.id),
            ('company_id', 'in', allowed_company_ids),
        ], limit=1)
        is_admin = user.has_group('base.group_system') or user.has_group('base.group_erp_manager') or user.has_group('hr_timesheet.group_timesheet_manager') or user.has_group('hr.group_hr_manager')
        is_hr = user.has_group('hr.group_hr_user') or user.has_group('hr_timesheet.group_timesheet_manager')
        is_approver = user.has_group('hr_timesheet.group_hr_timesheet_approver')

        target_emp_id = int(employee_id)

        # Verify target employee belongs to an allowed company
        target_emp = self.env['hr.employee'].browse(target_emp_id)
        if target_emp.company_id.id not in allowed_company_ids:
            raise UserError(_('You are not authorized to submit timesheets for this employee.'))

        is_manager = is_approver or (current_employee and target_emp_id in self.env['hr.employee'].search([
            ('parent_id', '=', current_employee.id),
            ('company_id', 'in', allowed_company_ids),
        ]).ids)

        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        current_week_start = self._get_current_week_start()

        if start_date < current_week_start and not (is_admin or is_hr or is_manager):
            raise UserError(_("Once a week is crossed, timesheets for the previous week cannot be submitted."))

        end_date = start_date + timedelta(days=6)
        lines = self.env['account.analytic.line'].search([
            ('employee_id', '=', target_emp_id),
            ('company_id', 'in', allowed_company_ids),
            ('date', '>=', start_date),
            ('date', '<=', end_date),
            ('state', '=', 'draft'),
        ])
        if lines:
            lines.action_submit()
            total_hours = sum(lines.mapped('unit_amount'))
            period_str = f"{start_date.strftime('%d %b %Y')} to {end_date.strftime('%d %b %Y')}"
            self._send_timesheet_email_notification(target_emp, period_str, round(total_hours, 2), 'submit')
        return True

    @api.model
    def approve_weekly_timesheet(self, employee_id, start_date_str):
        """Approve all submitted timesheets for this employee and week."""
        user = self.env.user
        allowed_company_ids = self.env.companies.ids
        current_employee = self.env['hr.employee'].search([
            ('user_id', '=', user.id),
            ('company_id', 'in', allowed_company_ids),
        ], limit=1)
        is_admin = user.has_group('base.group_system') or user.has_group('base.group_erp_manager') or user.has_group('hr_timesheet.group_timesheet_manager') or user.has_group('hr.group_hr_manager')
        is_hr = user.has_group('hr.group_hr_user') or user.has_group('hr_timesheet.group_timesheet_manager')
        is_approver = user.has_group('hr_timesheet.group_hr_timesheet_approver')
        target_emp_id = int(employee_id)

        # Verify target employee belongs to an allowed company
        target_emp = self.env['hr.employee'].browse(target_emp_id)
        if target_emp.company_id.id not in allowed_company_ids:
            raise UserError(_('You are not authorized to approve timesheets for this employee.'))

        is_manager = is_approver or (current_employee and target_emp_id in self.env['hr.employee'].search([
            ('parent_id', '=', current_employee.id),
            ('company_id', 'in', allowed_company_ids),
        ]).ids)

        if not (is_admin or is_hr or is_manager):
            raise UserError(_('Only the employee\'s manager, HR officers, or System Admins can approve timesheets.'))

        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = start_date + timedelta(days=6)
        lines = self.env['account.analytic.line'].search([
            ('employee_id', '=', target_emp_id),
            ('company_id', 'in', allowed_company_ids),
            ('date', '>=', start_date),
            ('date', '<=', end_date),
            ('state', '=', 'submitted'),
        ])
        if lines:
            lines.action_approve()
            total_hours = sum(lines.mapped('unit_amount'))
            period_str = f"{start_date.strftime('%d %b %Y')} to {end_date.strftime('%d %b %Y')}"
            approver_name = current_employee.name if current_employee else user.name
            self._send_timesheet_email_notification(target_emp, period_str, round(total_hours, 2), 'approve', approver_name=approver_name)
        return True

    @api.model
    def refuse_weekly_timesheet(self, employee_id, start_date_str):
        """Refuse all submitted timesheets for this employee and week."""
        user = self.env.user
        allowed_company_ids = self.env.companies.ids
        current_employee = self.env['hr.employee'].search([
            ('user_id', '=', user.id),
            ('company_id', 'in', allowed_company_ids),
        ], limit=1)
        is_admin = user.has_group('base.group_system') or user.has_group('base.group_erp_manager') or user.has_group('hr_timesheet.group_timesheet_manager') or user.has_group('hr.group_hr_manager')
        is_hr = user.has_group('hr.group_hr_user') or user.has_group('hr_timesheet.group_timesheet_manager')
        is_approver = user.has_group('hr_timesheet.group_hr_timesheet_approver')
        target_emp_id = int(employee_id)

        # Verify target employee belongs to an allowed company
        target_emp = self.env['hr.employee'].browse(target_emp_id)
        if target_emp.company_id.id not in allowed_company_ids:
            raise UserError(_('You are not authorized to refuse timesheets for this employee.'))

        is_manager = is_approver or (current_employee and target_emp_id in self.env['hr.employee'].search([
            ('parent_id', '=', current_employee.id),
            ('company_id', 'in', allowed_company_ids),
        ]).ids)

        if not (is_admin or is_hr or is_manager):
            raise UserError(_('Only the employee\'s manager, HR officers, or System Admins can refuse timesheets.'))

        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = start_date + timedelta(days=6)
        lines = self.env['account.analytic.line'].search([
            ('employee_id', '=', target_emp_id),
            ('company_id', 'in', allowed_company_ids),
            ('date', '>=', start_date),
            ('date', '<=', end_date),
            ('state', '=', 'submitted'),
        ])
        if lines:
            lines.action_refuse()
            total_hours = sum(lines.mapped('unit_amount'))
            period_str = f"{start_date.strftime('%d %b %Y')} to {end_date.strftime('%d %b %Y')}"
            approver_name = current_employee.name if current_employee else user.name
            self._send_timesheet_email_notification(target_emp, period_str, round(total_hours, 2), 'refuse', approver_name=approver_name)
        return True

    @api.model
    def _send_timesheet_email_notification(self, employee, date_range_str, total_hours, action_type, approver_name=None):
        """
        Send email notifications for timesheet submission, approval, and refusal.
        action_type: 'submit' (notify manager), 'approve' (notify employee), 'refuse' (notify employee)
        """
        if not employee:
            return

        company = employee.company_id or self.env.company

        try:
            if action_type == 'submit':
                # Notify Manager
                manager = employee.parent_id
                manager_email = manager.work_email or (manager.user_id and manager.user_id.email) if manager else False
                if not manager_email:
                    _logger.info(f"No manager email found for employee {employee.name}'s manager ({manager.name if manager else 'None'})")
                    return

                subject = f"[Timesheet Approval Request] {employee.name} submitted timesheet for {date_range_str}"
                body_html = f"""
                    <div style="font-family: Arial, sans-serif; padding: 20px; color: #333; max-width: 600px; border: 1px solid #e2e8f0; border-radius: 8px;">
                        <h2 style="color: #4f46e5; margin-top: 0;">Timesheet Submitted for Approval</h2>
                        <p>Dear <strong>{manager.name}</strong>,</p>
                        <p>Employee <strong>{employee.name}</strong> ({employee.department_id.name or 'General'}) has submitted their timesheet for review and approval.</p>
                        <table style="width: 100%; border-collapse: collapse; margin: 15px 0;">
                            <tr style="background: #f8fafc;"><th style="padding: 10px; border: 1px solid #e2e8f0; text-align: left;">Employee Name</th><td style="padding: 10px; border: 1px solid #e2e8f0;">{employee.name}</td></tr>
                            <tr><th style="padding: 10px; border: 1px solid #e2e8f0; text-align: left;">Department</th><td style="padding: 10px; border: 1px solid #e2e8f0;">{employee.department_id.name or 'N/A'}</td></tr>
                            <tr style="background: #f8fafc;"><th style="padding: 10px; border: 1px solid #e2e8f0; text-align: left;">Period / Dates</th><td style="padding: 10px; border: 1px solid #e2e8f0;">{date_range_str}</td></tr>
                            <tr><th style="padding: 10px; border: 1px solid #e2e8f0; text-align: left;">Total Logged Hours</th><td style="padding: 10px; border: 1px solid #e2e8f0;"><strong style="color: #4f46e5;">{total_hours} hrs</strong></td></tr>
                        </table>
                        <p>Kindly log in to your Odoo Timesheet Dashboard to approve or refuse this submission.</p>
                        <br/>
                        <p style="font-size: 12px; color: #64748b;">This is an automated notification from {company.name} Timesheet System.</p>
                    </div>
                """
                self.env['mail.mail'].sudo().create({
                    'subject': subject,
                    'body_html': body_html,
                    'email_to': manager_email,
                    'email_from': company.email or self.env.user.email_formatted,
                }).send()

            elif action_type == 'approve':
                # Notify Employee
                emp_email = employee.work_email or (employee.user_id and employee.user_id.email)
                if not emp_email:
                    return

                subject = f"[Timesheet Approved] Your timesheet for {date_range_str} has been approved"
                body_html = f"""
                    <div style="font-family: Arial, sans-serif; padding: 20px; color: #333; max-width: 600px; border: 1px solid #e2e8f0; border-radius: 8px;">
                        <h2 style="color: #10b981; margin-top: 0;">Timesheet Approved</h2>
                        <p>Dear <strong>{employee.name}</strong>,</p>
                        <p>Your timesheet for <strong>{date_range_str}</strong> ({total_hours} hrs) has been <span style="color: #10b981; font-weight: bold;">APPROVED</span> by <strong>{approver_name or 'Management'}</strong>.</p>
                        <br/>
                        <p style="font-size: 12px; color: #64748b;">This is an automated notification from {company.name} Timesheet System.</p>
                    </div>
                """
                self.env['mail.mail'].sudo().create({
                    'subject': subject,
                    'body_html': body_html,
                    'email_to': emp_email,
                    'email_from': company.email or self.env.user.email_formatted,
                }).send()

            elif action_type == 'refuse':
                # Notify Employee
                emp_email = employee.work_email or (employee.user_id and employee.user_id.email)
                if not emp_email:
                    return

                subject = f"[Timesheet Refused] Your timesheet for {date_range_str} has been refused"
                body_html = f"""
                    <div style="font-family: Arial, sans-serif; padding: 20px; color: #333; max-width: 600px; border: 1px solid #e2e8f0; border-radius: 8px;">
                        <h2 style="color: #ef4444; margin-top: 0;">Timesheet Refused</h2>
                        <p>Dear <strong>{employee.name}</strong>,</p>
                        <p>Your timesheet for <strong>{date_range_str}</strong> ({total_hours} hrs) has been <span style="color: #ef4444; font-weight: bold;">REFUSED / REJECTED</span> by <strong>{approver_name or 'Management'}</strong>.</p>
                        <p>Please review your timesheet lines and contact your reporting manager if you have questions.</p>
                        <br/>
                        <p style="font-size: 12px; color: #64748b;">This is an automated notification from {company.name} Timesheet System.</p>
                    </div>
                """
                self.env['mail.mail'].sudo().create({
                    'subject': subject,
                    'body_html': body_html,
                    'email_to': emp_email,
                    'email_from': company.email or self.env.user.email_formatted,
                }).send()

        except Exception as e:
            _logger.error(f"Failed to send timesheet notification email ({action_type}) for employee {employee.name}: {str(e)}")
