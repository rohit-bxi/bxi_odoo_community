# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import date, timedelta


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

    @api.constrains('date')
    def _check_past_week_lock(self):
        """Block standard employees from adding or modifying timesheets for past weeks."""
        today = date.today()
        offset = (today.weekday() + 1) % 7
        current_week_start = today - timedelta(days=offset)

        user = self.env.user
        is_admin = user.has_group('base.group_system') or user.has_group('base.group_erp_manager')
        is_hr = user.has_group('hr.group_hr_user') or user.has_group('hr.group_hr_manager')
        current_employee = self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)

        for rec in self:
            if rec.date and rec.date < current_week_start:
                raise UserError(_("Timesheets for previous weeks (before %s) cannot be created, modified, or submitted.") % current_week_start.strftime('%Y-%m-%d'))

    # NOTE: Multiple timesheet lines per day are allowed (different project/task combos).
    # A per-day uniqueness constraint is NOT enforced here.

    @api.constrains('unit_amount')
    def _check_max_hours_per_day(self):
        """Block users from logging more than 9 hours for a single day."""
        for rec in self:
            if rec.unit_amount > 9.0:
                raise UserError(_("You cannot log more than 9 hours for a single day (%s).") % rec.date.strftime('%Y-%m-%d'))

    def action_submit(self):
        today = date.today()
        offset = (today.weekday() + 1) % 7
        current_week_start = today - timedelta(days=offset)

        user = self.env.user
        is_admin = user.has_group('base.group_system') or user.has_group('base.group_erp_manager')
        is_hr = user.has_group('hr.group_hr_user') or user.has_group('hr.group_hr_manager')
        current_employee = self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)

        submitted_recs = self.filtered(lambda r: r.state == 'draft')
        for rec in self:
            if rec.date and rec.date < current_week_start:
                is_manager = current_employee and rec.employee_id.parent_id.id == current_employee.id
                if not (is_admin or is_hr or is_manager):
                    raise UserError(_("Timesheets for previous weeks cannot be submitted for approval."))

            if rec.state == 'draft':
                rec.state = 'submitted'

        # Send email notifications grouped by employee
        if submitted_recs:
            dashboard_model = self.env['bxi.timesheet.dashboard']
            for emp in submitted_recs.mapped('employee_id'):
                emp_lines = submitted_recs.filtered(lambda l: l.employee_id == emp)
                total_hours = sum(emp_lines.mapped('unit_amount'))
                dates = emp_lines.mapped('date')
                min_date = min(dates) if dates else today
                max_date = max(dates) if dates else today
                period_str = f"{min_date.strftime('%d %b %Y')} to {max_date.strftime('%d %b %Y')}" if min_date != max_date else min_date.strftime('%d %b %Y')
                dashboard_model._send_timesheet_email_notification(emp, period_str, round(total_hours, 2), 'submit')

        return True

    def action_approve(self):
        user = self.env.user
        is_admin = user.has_group('base.group_system') or user.has_group('base.group_erp_manager')
        is_hr = user.has_group('hr.group_hr_user') or user.has_group('hr.group_hr_manager')

        approved_recs = self.env['account.analytic.line']
        for rec in self:
            current_employee = self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
            is_manager = current_employee and rec.employee_id.parent_id.id == current_employee.id

            if not (is_admin or is_hr or is_manager):
                raise UserError(_("Only the employee's manager, HR officers, or System Admins can approve timesheets."))

            if rec.state == 'submitted':
                rec.state = 'approved'
                approved_recs |= rec

        if approved_recs:
            dashboard_model = self.env['bxi.timesheet.dashboard']
            current_employee = self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
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
        is_admin = user.has_group('base.group_system') or user.has_group('base.group_erp_manager')
        is_hr = user.has_group('hr.group_hr_user') or user.has_group('hr.group_hr_manager')

        refused_recs = self.env['account.analytic.line']
        for rec in self:
            current_employee = self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
            is_manager = current_employee and rec.employee_id.parent_id.id == current_employee.id

            if not (is_admin or is_hr or is_manager):
                raise UserError(_("Only the employee's manager, HR officers, or System Admins can refuse timesheets."))

            if rec.state == 'submitted':
                rec.state = 'refused'
                refused_recs |= rec

        if refused_recs:
            dashboard_model = self.env['bxi.timesheet.dashboard']
            current_employee = self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
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
        Daily check for employees who haven't logged timesheets for 7 consecutive days.
        Creates a 1-day Leave Without Pay on the 8th day (today).
        """
        import logging
        _logger = logging.getLogger(__name__)
        
        today = fields.Date.today()
        start_date = today - timedelta(days=7)
        end_date = today - timedelta(days=1)
        
        employees = self.env['hr.employee'].sudo().search([('active', '=', True)])
        
        for emp in employees:
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
                _logger.warning("LOP leave type (code='LOP') not found for employee %s (company: %s). Please configure it.", emp.name, emp.company_id.name)
                continue

            logged_days = self.env['account.analytic.line'].sudo().search([
                ('employee_id', '=', emp.id),
                ('date', '>=', start_date),
                ('date', '<=', end_date),
                ('unit_amount', '>', 0.0)
            ])
            
            distinct_logged_dates = set(logged_days.mapped('date'))
            
            if len(distinct_logged_dates) == 0:
                existing_leave = self.env['hr.leave'].sudo().search([
                    ('employee_id', '=', emp.id),
                    ('request_date_from', '=', today),
                    ('state', '!=', 'refuse'),
                ], limit=1)
                
                if not existing_leave:
                    try:
                        self.env['hr.leave'].sudo().with_context(
                            allowed_company_ids=[emp.company_id.id]
                        ).create({
                            'employee_id': emp.id,
                            'holiday_status_id': unpaid_type.id,
                            'request_date_from': today,
                            'request_date_to': today,
                            'number_of_days': 1.0,
                            'company_id': emp.company_id.id,
                            'name': 'Auto-created: Leave Without Pay (No timesheet logged for 7 days)',
                        })
                        _logger.info(f"Auto-created Unpaid Leave for employee {emp.name} on {today}")
                    except Exception as e:
                        _logger.error(f"Failed to auto-create Unpaid Leave for employee {emp.name}: {str(e)}")
        return True
