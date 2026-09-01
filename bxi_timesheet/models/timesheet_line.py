# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import date, timedelta

# Threshold for role band applicability (inclusive lower bound)
ROLE_BAND_THRESHOLD = 8


class AccountAnalyticLine(models.Model):
    """
    Inherits Odoo's standard timesheet line to add approval states, actions,
    and past week locking constraints.
    """
    _inherit = 'account.analytic.line'

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('refused', 'Refused')
    ], string='Approval Status', default='draft', required=True, copy=False, index=True)

    remarks = fields.Text(string='Manager Remarks', copy=False)

    @api.constrains('date')
    def _check_past_week_lock(self):
        """Block standard employees from adding or modifying timesheets for past weeks."""
        today = date.today()
        offset = (today.weekday() + 1) % 7
        current_week_start = today - timedelta(days=offset)

        user = self.env.user
        is_admin = user.has_group('base.group_system') or user.has_group('base.group_erp_manager')
        is_hr = user.has_group('hr.group_hr_user') or user.has_group('hr.group_hr_manager')
        current_employee = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)

        for rec in self:
            # Time off requests / holidays are managed via the Time Off app; skip past-week lock check
            if hasattr(rec, 'holiday_id') and rec.holiday_id:
                continue

            # Only enforce past-week lock for employees whose role_band is below the threshold.
            # Employees with role_band >= 8 are exempt from these restrictions.
            try:
                rb_val = int(rec.employee_id.role_band) if rec.employee_id and rec.employee_id.role_band else None
            except Exception:
                rb_val = None

            if rb_val is not None and rb_val >= ROLE_BAND_THRESHOLD:
                continue

            if rec.date and rec.date < current_week_start:
                raise UserError(_("Timesheets for previous weeks (before %s) cannot be created, modified, or submitted.") % current_week_start.strftime('%Y-%m-%d'))

    @api.constrains('employee_id', 'date')
    def _check_one_entry_per_day(self):
        """Block users from creating more than 1 timesheet entry for a single day."""
        for rec in self:
            # Time off requests / holidays are managed via the Time Off app; skip one-entry check
            if hasattr(rec, 'holiday_id') and rec.holiday_id:
                continue

            # Only enforce the one-entry-per-day restriction for employees with role_band < 8.
            try:
                rb_val = int(rec.employee_id.role_band) if rec.employee_id and rec.employee_id.role_band else None
            except Exception:
                rb_val = None

            if rb_val is not None and rb_val >= ROLE_BAND_THRESHOLD:
                continue

            if rec.employee_id and rec.date:
                domain = [
                    ('employee_id', '=', rec.employee_id.id),
                    ('date', '=', rec.date),
                    ('id', '!=', rec.id),
                ]
                if 'holiday_id' in self.env['account.analytic.line']._fields:
                    domain.append(('holiday_id', '=', False))
                existing = self.env['account.analytic.line'].sudo().search(domain, limit=1)
                if existing:
                    raise UserError(_("Only one timesheet entry is allowed per day (%s) for employee %s.") % (
                        rec.date.strftime('%Y-%m-%d'), rec.employee_id.name
                    ))

    @api.constrains('unit_amount', 'employee_id', 'date')
    def _check_max_hours_per_day(self):
        """Block users from logging more than 9 hours for a single day."""
        for rec in self:
            # Skip check for time off lines
            if hasattr(rec, 'holiday_id') and rec.holiday_id:
                continue

            # Only enforce the per-day hours cap for employees with role_band < 8.
            try:
                rb_val = int(rec.employee_id.role_band) if rec.employee_id and rec.employee_id.role_band else None
            except Exception:
                rb_val = None

            if rb_val is not None and rb_val >= ROLE_BAND_THRESHOLD:
                continue

            if rec.employee_id and rec.date:
                domain = [
                    ('employee_id', '=', rec.employee_id.id),
                    ('date', '=', rec.date),
                ]
                if 'holiday_id' in self.env['account.analytic.line']._fields:
                    domain.append(('holiday_id', '=', False))
                day_lines = self.env['account.analytic.line'].sudo().search(domain)
                total_hours = sum(day_lines.mapped('unit_amount'))
                if total_hours > 9.0:
                    raise UserError(_("You cannot log more than 9 hours for a single day (%s).") % rec.date.strftime('%Y-%m-%d'))

    def _check_can_write(self, values):
        """
        Allow updating approval workflow fields (state, remarks) on timesheets linked
        to time off requests, while preserving Odoo's core check against modifying hours/project/dates.
        """
        allowed_fields = {'state', 'remarks'}
        if set(values.keys()).issubset(allowed_fields):
            return True
        if hasattr(super(), '_check_can_write'):
            return super()._check_can_write(values)
        return True

    def write(self, values):
        """
        Allow approval status and remarks updates on timesheet lines linked to Time Off requests (holiday_id)
        by using superuser mode when updating only approval fields.
        """
        allowed_fields = {'state', 'remarks'}
        if set(values.keys()).issubset(allowed_fields) and any(getattr(line, 'holiday_id', False) for line in self):
            return super(AccountAnalyticLine, self.sudo()).write(values)
        return super().write(values)

    def action_submit(self):
        today = date.today()
        offset = (today.weekday() + 1) % 7
        current_week_start = today - timedelta(days=offset)

        user = self.env.user
        is_admin = user.has_group('base.group_system') or user.has_group('base.group_erp_manager') or user.has_group('hr_timesheet.group_timesheet_manager')
        is_hr = user.has_group('hr.group_hr_user') or user.has_group('hr.group_hr_manager') or user.has_group('hr_timesheet.group_hr_timesheet_approver')
        current_employee = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)

        submitted_recs = self.filtered(lambda r: r.state == 'draft' and not (hasattr(r, 'holiday_id') and r.holiday_id))
        for rec in self:
            # Bypass timesheets linked to time off requests completely
            if hasattr(rec, 'holiday_id') and rec.holiday_id:
                continue

            if rec.date and rec.date < current_week_start:
                # Only enforce past-week submission restriction for employees with role_band < 8.
                try:
                    rb_val = int(rec.employee_id.role_band) if rec.employee_id and rec.employee_id.role_band else None
                except Exception:
                    rb_val = None

                if rb_val is not None and rb_val < ROLE_BAND_THRESHOLD:
                    is_manager = current_employee and rec.employee_id.parent_id.id == current_employee.id
                    if not (is_admin or is_hr or is_manager):
                        raise UserError(_("Timesheets for previous weeks cannot be submitted for approval."))

            # Check if another timesheet for the same employee & date is already submitted or approved
            if rec.state == 'draft':
                domain = [
                    ('employee_id', '=', rec.employee_id.id),
                    ('date', '=', rec.date),
                    ('state', 'in', ['submitted', 'approved']),
                    ('id', '!=', rec.id)
                ]
                if 'holiday_id' in self.env['account.analytic.line']._fields:
                    domain.append(('holiday_id', '=', False))
                already_submitted = self.env['account.analytic.line'].sudo().search(domain, limit=1)
                if already_submitted:
                    status_str = "submitted for approval" if already_submitted.state == 'submitted' else "approved"
                    raise UserError(_("Timesheet for %s on %s has already been %s.") % (rec.employee_id.name, rec.date.strftime('%Y-%m-%d'), status_str))

                rec.sudo().write({'state': 'submitted'})
        return True

    def action_approve(self):
        user = self.env.user
        is_admin = user.has_group('base.group_system') or user.has_group('base.group_erp_manager') or user.has_group('hr_timesheet.group_timesheet_manager')
        is_hr_manager = user.has_group('hr.group_hr_manager')

        approved_recs = self.env['account.analytic.line']
        for rec in self:
            # Bypass timesheets linked to time off requests completely
            if hasattr(rec, 'holiday_id') and rec.holiday_id:
                continue

            current_employee = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)

            # Block self-approval for non-admins
            if current_employee and rec.employee_id.id == current_employee.id and not is_admin:
                raise UserError(_("You are not authorized to approve your own timesheet. Only your reporting manager can approve or refuse your timesheet."))

            is_manager = (current_employee and rec.employee_id.parent_id.id == current_employee.id) or is_hr_manager or is_admin

            if not is_manager:
                raise UserError(_("You are not authorized for the approval of timesheets for %s. Only their reporting manager can approve or refuse them.") % rec.employee_id.name)

            if rec.state == 'submitted':
                rec.sudo().write({'state': 'approved'})
                approved_recs |= rec

        if approved_recs:
            dashboard_model = self.env['bxi.timesheet.dashboard']
            current_employee = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
            approver_name = current_employee.name if current_employee else user.name
            for emp in approved_recs.mapped('employee_id'):
                emp_lines = approved_recs.filtered(lambda l: l.employee_id == emp)
                total_hours = sum(emp_lines.mapped('unit_amount'))
                dates = emp_lines.mapped('date')
                min_date = min(dates) if dates else date.today()
                max_date = max(dates) if dates else date.today()
                period_str = f"{min_date.strftime('%d %b %Y')} to {max_date.strftime('%d %b %Y')}" if min_date != max_date else min_date.strftime('%d %b %Y')
                dashboard_model._send_timesheet_email_notification(emp, period_str, round(total_hours, 2), 'approve', approver_name=approver_name)

        return True

    def action_refuse(self):
        user = self.env.user
        is_admin = user.has_group('base.group_system') or user.has_group('base.group_erp_manager') or user.has_group('hr_timesheet.group_timesheet_manager')
        is_hr_manager = user.has_group('hr.group_hr_manager')

        refused_recs = self.env['account.analytic.line']
        for rec in self:
            # Bypass timesheets linked to time off requests completely
            if hasattr(rec, 'holiday_id') and rec.holiday_id:
                continue

            current_employee = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)

            # Block self-refusal for non-admins
            if current_employee and rec.employee_id.id == current_employee.id and not is_admin:
                raise UserError(_("You are not authorized to refuse your own timesheet. Only your reporting manager can approve or refuse your timesheet."))

            is_manager = (current_employee and rec.employee_id.parent_id.id == current_employee.id) or is_hr_manager or is_admin

            if not is_manager:
                raise UserError(_("You are not authorized for the refusal of timesheets for %s. Only their reporting manager can approve or refuse them.") % rec.employee_id.name)

            if rec.state == 'submitted':
                rec.sudo().write({'state': 'refused'})
                refused_recs |= rec

        if refused_recs:
            dashboard_model = self.env['bxi.timesheet.dashboard']
            current_employee = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
            approver_name = current_employee.name if current_employee else user.name
            for emp in refused_recs.mapped('employee_id'):
                emp_lines = refused_recs.filtered(lambda l: l.employee_id == emp)
                total_hours = sum(emp_lines.mapped('unit_amount'))
                dates = emp_lines.mapped('date')
                min_date = min(dates) if dates else date.today()
                max_date = max(dates) if dates else date.today()
                period_str = f"{min_date.strftime('%d %b %Y')} to {max_date.strftime('%d %b %Y')}" if min_date != max_date else min_date.strftime('%d %b %Y')
                dashboard_model._send_timesheet_email_notification(emp, period_str, round(total_hours, 2), 'refuse', approver_name=approver_name)

        return True

    @api.model
    def _cron_check_unpaid_leaves(self):
        """
        Daily check for employees who haven't logged timesheets for 6 consecutive days.
        Creates a 1-day Leave Without Pay on the 7th day (today).
        """
        import logging
        _logger = logging.getLogger(__name__)
        
        today = fields.Date.today()
        
        # Do not auto-apply leave on weekends; only apply on weekdays
        if today.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
            _logger.info("BXI Timesheet Cron: Weekend detected (%s), skipping auto LWP creation.", today.strftime('%A'))
            return True

        # Build the last 6 working days excluding Sundays
        working_days = []
        check_date = today - timedelta(days=1)
        while len(working_days) < 6:
            if check_date.weekday() != 6:  # Sunday excluded
                working_days.append(check_date)
            check_date -= timedelta(days=1)

        employees = self.env['hr.employee'].sudo().search([('active', '=', True)])

        for emp in employees:
            # Apply auto-LWP only for employees with role_band < 8.
            try:
                emp_rb = int(emp.role_band) if emp.role_band else None
            except Exception:
                emp_rb = None

            if emp_rb is not None and emp_rb >= ROLE_BAND_THRESHOLD:
                continue
            # Search by exact leave code 'LOP': company-specific first, then global
            unpaid_type = self.env['hr.leave.type'].sudo().search([
                ('company_id', '=', emp.company_id.id),
                ('code', '=', 'LOP'),
            ], limit=1)
            if not unpaid_type:
                unpaid_type = self.env['hr.leave.type'].sudo().search([
                    ('company_id', '=', False),
                    ('code', '=', 'LOP'),
                ], limit=1)

            if not unpaid_type:
                _logger.warning(
                    "LOP leave type (code='LOP') not found for employee %s (company: %s). Please configure it.",
                    emp.name,
                    emp.company_id.name,
                )
                continue

            logged_days = self.env['account.analytic.line'].sudo().search([
                ('employee_id', '=', emp.id),
                ('date', 'in', working_days),
                ('unit_amount', '>', 0.0),
            ])

            distinct_logged_dates = set(logged_days.mapped('date'))

            # Treat approved/validated leaves as presence for that day (do not count as missing)
            approved_leaves = self.env['hr.leave'].sudo().search([
                ('employee_id', '=', emp.id),
                ('request_date_from', '<=', max(working_days)),
                ('request_date_to', '>=', min(working_days)),
                ('state', 'not in', ('draft', 'cancel', 'refuse')),
            ])
            for lv in approved_leaves:
                # Add each covered date to the distinct set
                start_dt = lv.request_date_from
                end_dt = lv.request_date_to
                cur = start_dt
                while cur <= end_dt:
                    if cur in working_days:
                        distinct_logged_dates.add(cur)
                    cur = cur + timedelta(days=1)

            if len(distinct_logged_dates) == 0:
                existing_leave = self.env['hr.leave'].sudo().search([
                    ('employee_id', '=', emp.id),
                    ('request_date_from', '=', today),
                    ('state', '!=', 'refuse'),
                ], limit=1)
                
                if not existing_leave:
                    try:
                        leave = self.env['hr.leave'].sudo().with_context(
                            allowed_company_ids=[emp.company_id.id]
                        ).create({
                            'employee_id': emp.id,
                            'holiday_status_id': unpaid_type.id,
                            'request_date_from': today,
                            'request_date_to': today,
                            'number_of_days': 1.0,
                            'company_id': emp.company_id.id,
                            'name': 'Auto-created: Leave Without Pay (No timesheet logged for 6 working days)',
                        })
                        # Auto-create the LOP and validate it immediately so it is not held for
                        # a separate manager/HR approval step.
                        if hasattr(leave, 'action_validate'):
                            leave.action_validate()
                        elif hasattr(leave, 'action_approve'):
                            leave.action_approve()
                        elif hasattr(leave, 'action_submit'):
                            leave.action_submit()
                        elif hasattr(leave, 'action_confirm'):
                            leave.action_confirm()
                        _logger.info(
                            f"Auto-created and validated Unpaid Leave for employee {emp.name} on {today}"
                        )
                    except Exception as e:
                        _logger.error(
                            f"Failed to auto-create Unpaid Leave for employee {emp.name}: {str(e)}"
                        )
        return True

    @api.model
    def _cron_send_consolidated_approval_emails(self):
        """
        Daily scheduled action to send consolidated email notifications to reporting managers
        containing all submitted timesheets pending approval for their direct reports.
        """
        import logging
        _logger = logging.getLogger(__name__)

        submitted_lines = self.sudo().search([('state', '=', 'submitted')])
        if not submitted_lines:
            _logger.info("BXI Timesheet Cron: No submitted timesheets pending approval.")
            return True

        # Group lines by employee
        employee_data = {}
        for emp in submitted_lines.mapped('employee_id'):
            emp_lines = submitted_lines.filtered(lambda l: l.employee_id == emp)
            total_hours = sum(emp_lines.mapped('unit_amount'))
            dates = emp_lines.mapped('date')
            today_date = fields.Date.today()
            min_date = min(dates) if dates else today_date
            max_date = max(dates) if dates else today_date
            period_str = f"{min_date.strftime('%d %b %Y')} to {max_date.strftime('%d %b %Y')}" if min_date != max_date else min_date.strftime('%d %b %Y')

            employee_data[emp] = {
                'total_hours': round(total_hours, 2),
                'period_str': period_str,
                'department': emp.department_id.name or 'N/A',
            }

        # Group employees by manager
        manager_employees = {}
        for emp in employee_data.keys():
            manager = emp.parent_id
            if manager not in manager_employees:
                manager_employees[manager] = []
            manager_employees[manager].append(emp)

        # For each manager, compose and send a single consolidated email
        for manager, emp_list in manager_employees.items():
            company = manager.company_id if manager and manager.company_id else self.env.company
            manager_name = manager.name if manager else 'Manager'
            manager_email = (manager.work_email or (manager.user_id and manager.user_id.email)) if manager else False

            if not manager_email:
                _logger.warning(
                    f"BXI Timesheet Cron: Direct manager {manager_name} has no configured email. Skipping consolidated notification for their team."
                )
                continue

            # Build HTML table rows for all employees under this manager
            rows_html = ""
            for idx, emp in enumerate(emp_list):
                info = employee_data[emp]
                bg_style = "background: #f8fafc;" if idx % 2 == 0 else ""
                rows_html += f"""
                <tr style="{bg_style}">
                    <td style="padding: 10px 14px; border: 1px solid #cbd5e1; font-weight: bold;">{emp.name}</td>
                    <td style="padding: 10px 14px; border: 1px solid #cbd5e1;">{info['department']}</td>
                    <td style="padding: 10px 14px; border: 1px solid #cbd5e1;">{info['period_str']}</td>
                    <td style="padding: 10px 14px; border: 1px solid #cbd5e1; text-align: right;"><strong style="color: #4f46e5;">{info['total_hours']} hrs</strong></td>
                </tr>
                """

            subject = f"[Timesheet Approval Required] Consolidated Submissions Summary ({fields.Date.today().strftime('%d %b %Y')})"
            body_html = f"""
                <div style="font-family: 'Segoe UI', Helvetica, Arial, sans-serif; padding: 25px; color: #1e293b; max-width: 650px; border: 1px solid #e2e8f0; border-radius: 12px; background-color: #ffffff;">
                    <h2 style="color: #4f46e5; margin-top: 0; font-size: 20px;">Timesheet Submissions Pending Approval</h2>
                    <p style="font-size: 14px; line-height: 1.6;">Dear <strong>{manager_name}</strong>,</p>
                    <p style="font-size: 14px; line-height: 1.6;">The following employees under your supervision have submitted their timesheets for approval. Please review the summary below:</p>
                    
                    <table style="width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 13px;">
                        <thead>
                            <tr style="background: #4f46e5; color: #ffffff;">
                                <th style="padding: 10px 14px; border: 1px solid #4f46e5; text-align: left;">Employee Name</th>
                                <th style="padding: 10px 14px; border: 1px solid #4f46e5; text-align: left;">Department</th>
                                <th style="padding: 10px 14px; border: 1px solid #4f46e5; text-align: left;">Period</th>
                                <th style="padding: 10px 14px; border: 1px solid #4f46e5; text-align: right;">Total Hours</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows_html}
                        </tbody>
                    </table>

                    <p style="font-size: 14px; line-height: 1.6;">Kindly log in to your Odoo Timesheet Dashboard to review and approve these submissions.</p>
                    <hr style="border: none; border-top: 1px solid #e2e8f0; margin-top: 25px;"/>
                    <p style="font-size: 12px; color: #64748b; margin-bottom: 0;">This is an automated consolidated notification from {company.name} Timesheet System.</p>
                </div>
            """

            try:
                self.env['mail.mail'].sudo().create({
                    'subject': subject,
                    'body_html': body_html,
                    'email_to': manager_email,
                    'email_from': 'hrsupport@bxitech.com',
                }).send()
                _logger.info("BXI Timesheet Cron: Sent consolidated timesheet approval email to %s for %d employees", manager_email, len(emp_list))
            except Exception as e:
                _logger.error("BXI Timesheet Cron: Failed to send consolidated email to %s: %s", manager_email, str(e))

        return True
