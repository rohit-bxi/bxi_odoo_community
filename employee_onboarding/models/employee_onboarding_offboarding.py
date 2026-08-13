# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class EmployeeOnboardingOffboarding(models.Model):
    _name = 'employee.onboarding.offboarding'
    _description = 'Employee Onboarding / Offboarding'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    request_type_id = fields.Many2one(
        'boarding.request.type',
        string='Request Type',
        required=True,
        tracking=True,
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('in_progress', 'In Progress'),
            ('done', 'Done'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
    )

    # ── Employee Information ─────────────────────────────────────────────
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        tracking=True,
    )
    employee_code = fields.Char(
        string='Employee Code',
        readonly=True,
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        readonly=True,
    )
    position_id = fields.Many2one(
        'hr.job',
        string='Job Position',
        readonly=True,
    )
    manager_id = fields.Many2one(
        'hr.employee',
        string='Manager',
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        readonly=True,
        default=lambda self: self.env.company,
    )
    work_email = fields.Char(
        string='Work Email',
        readonly=True,
    )
    work_phone = fields.Char(
        string='Work Phone',
        readonly=True,
    )

    # ── Request Details ──────────────────────────────────────────────────
    resignation_id = fields.Many2one(
        'employee.resignation',
        string='Resignation',
        ondelete='set null',
        tracking=True,
    )
    request_date = fields.Date(
        string='Request Date',
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    effective_date = fields.Date(
        string='Effective Date',
        tracking=True,
    )
    reason = fields.Text(
        string='Reason / Remarks',
    )
    notes = fields.Html(
        string='Notes',
    )
    task_line_ids = fields.One2many(
        'employee.onboarding.task',
        'onboarding_id',
        string='Task Checklist',
    )

    # ── Sequence ─────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                request_type_id = vals.get('request_type_id')
                request_type_name = ''
                if request_type_id:
                    request_type_name = self.env['boarding.request.type'].browse(
                        request_type_id
                    ).name or ''
                if 'offboard' in request_type_name.lower().replace('-', '').replace(' ', ''):
                    vals['name'] = self.env['ir.sequence'].next_by_code(
                        'employee.offboarding.sequence'
                    ) or _('New')
                else:
                    vals['name'] = self.env['ir.sequence'].next_by_code(
                        'employee.onboarding.sequence'
                    ) or _('New')
        return super().create(vals_list)

    # ── Onchange ─────────────────────────────────────────────────────────
    @api.onchange('request_type_id')
    def _onchange_request_type_id(self):
        """Auto-fill task checklist from the selected request type's tasks."""
        self.task_line_ids = [(5, 0, 0)]
        if self.request_type_id and self.request_type_id.task_ids:
            lines = []
            for task in self.request_type_id.task_ids:
                lines.append((0, 0, {
                    'task': task.task,
                    'performed_by': task.performed_by.id if task.performed_by else False,
                    'sequence': task.sequence,
                    'status': 'incomplete',
                    'review': 'pending',
                }))
            self.task_line_ids = lines

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            emp = self.employee_id
            self.employee_code = emp.employee_code
            self.department_id = emp.department_id
            self.position_id = emp.job_id
            self.manager_id = emp.parent_id
            self.company_id = emp.company_id
            self.work_email = emp.work_email
            self.work_phone = emp.work_phone
        else:
            self.employee_code = False
            self.department_id = False
            self.position_id = False
            self.manager_id = False
            self.company_id = self.env.company
            self.work_email = False
            self.work_phone = False

    # ── Status Actions ───────────────────────────────────────────────────
    def action_in_progress(self):
        for rec in self:
            rec.state = 'in_progress'
            rec._send_consolidated_team_task_emails()

    def _send_consolidated_team_task_emails(self):
        for rec in self:
            if not rec.task_line_ids:
                continue

            # Group tasks by assigned team
            team_tasks = {}
            for line in rec.task_line_ids:
                if line.performed_by:
                    team_tasks.setdefault(line.performed_by, []).append(line)

            for team, tasks in team_tasks.items():
                if team.is_manager:
                    manager = rec.manager_id or rec.employee_id.parent_id
                    recipient_email = manager.work_email or manager.private_email if manager else False
                    recipient_name = manager.name if manager else team.name
                    if not recipient_email:
                        rec.message_post(
                            body=_("Could not send email notification to manager team '%s' because employee's manager (%s) has no email address configured.") % (
                                team.name, manager.name if manager else _('No Manager')
                            )
                        )
                        continue
                else:
                    recipient_email = team.email
                    recipient_name = team.name
                    if not recipient_email:
                        rec.message_post(
                            body=_("Could not send email notification to team '%s' because no email address is configured.") % team.name
                        )
                        continue

                subject = _("New Tasks Assigned: %s - %s (%s)") % (
                    rec.request_type_id.name or _('Request'),
                    rec.employee_id.name or '',
                    rec.name or ''
                )

                task_rows = ""
                for idx, task_line in enumerate(tasks, start=1):
                    status_label = dict(task_line._fields['status'].selection).get(task_line.status, task_line.status)
                    task_rows += f"""
                        <tr>
                            <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{idx}</td>
                            <td style="padding: 8px; border: 1px solid #ddd;">{task_line.task}</td>
                            <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{status_label}</td>
                        </tr>
                    """

                body_html = f"""
                    <div style="font-family: Arial, sans-serif; font-size: 14px; color: #333333; line-height: 1.5;">
                        <p>Hello <strong>{recipient_name}</strong>,</p>
                        <p>A new <strong>{rec.request_type_id.name or ''}</strong> request (Ref: <strong>{rec.name or ''}</strong>) has been raised for employee <strong>{rec.employee_id.name or ''}</strong>.</p>
                        <p>Please find below the consolidated list of tasks assigned to your team:</p>
                        <table style="border-collapse: collapse; width: 100%; max-width: 600px; margin-top: 10px; margin-bottom: 15px;">
                            <thead>
                                <tr style="background-color: #f2f2f2;">
                                    <th style="padding: 8px; border: 1px solid #ddd; width: 40px;">#</th>
                                    <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Task Description</th>
                                    <th style="padding: 8px; border: 1px solid #ddd; width: 100px;">Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                {task_rows}
                            </tbody>
                        </table>
                        <p>You are requested to perform all these respective tasks and once done, update the task status in the portal.</p>
                        <br/>
                        <p>Best regards,<br/><strong>{self.env.company.name}</strong></p>
                    </div>
                """

                mail_values = {
                    'subject': subject,
                    'body_html': body_html,
                    'email_to': recipient_email,
                    'email_from': self.env.user.email_formatted or self.env.company.email,
                    'model': 'employee.onboarding.offboarding',
                    'res_id': rec.id,
                }
                mail = self.env['mail.mail'].sudo().create(mail_values)
                mail.send()


    def action_done(self):

        for rec in self:
            rec.state = 'done'

    def action_cancel(self):
        for rec in self:
            rec.state = 'cancelled'

    def action_reset_to_draft(self):
        for rec in self:
            rec.state = 'draft'


class EmployeeOnboardingTask(models.Model):
    _name = 'employee.onboarding.task'
    _description = 'Employee Onboarding Task'
    _order = 'sequence, id'

    onboarding_id = fields.Many2one(
        'employee.onboarding.offboarding',
        string='Onboarding/Offboarding',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )
    task = fields.Char(
        string='Task',
        required=True,
    )
    performed_by = fields.Many2one(
        'request.type.team',
        string='Performed By',
        required=True,
    )
    status = fields.Selection(
        [
            ('incomplete', 'Incomplete'),
            ('completed', 'Completed'),
        ],
        string='Status',
        default='incomplete',
        required=True,
    )
    review = fields.Selection(
        [
            ('pending', 'Pending'),
            ('done', 'Done'),
        ],
        string='Review',
        default='pending',
        required=True,
    )
