# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class EmployeeOnboardingOffboarding(models.Model):
    _name = 'employee.onboarding.offboarding'
    _description = 'Employee Onboarding / Offboarding'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    active = fields.Boolean(
        string='Active',
        default=True,
        tracking=True,
    )
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
    employee_model = fields.Selection(
        related='request_type_id.employee_model',
        string='Employee Model',
        readonly=True,
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

    # ── Employee Onboarding Information ────────────────────────────────
    # Source: hr.bxi.employee
    employee_id = fields.Many2one(
        'hr.bxi.employee',
        string='Employee',
        tracking=True,
    )

    onboarding_department_id = fields.Many2one(
        'hr.department',
        related='employee_id.department_id',
        readonly=True,
    )

    onboarding_position_id = fields.Many2one(
        'hr.job',
        related='employee_id.job_id',
        readonly=True,
    )

    onboarding_job_title = fields.Char(
        related='employee_id.job_title',
        readonly=True,
    )

    onboarding_employee_code = fields.Char(
        related='employee_id.employee_code',
        readonly=True,
    )

    onboarding_role_band = fields.Char(
        related='employee_id.role_band',
        readonly=True,
    )

    onboarding_emp_category = fields.Char(
        related='employee_id.emp_category',
        readonly=True,
    )

    onboarding_emp_skill_category = fields.Char(
        related='employee_id.emp_skill_category',
        readonly=True,
    )
    onboarding_manager_id = fields.Many2one(
        'hr.employee',
        related='employee_id.reporting_manager_id',
        readonly=True,
    )
    onboarding_company_id = fields.Many2one(
        related='employee_id.company_id',
        string='Company',
        readonly=True,
    )
    onboarding_phone_number = fields.Char(
        related='employee_id.contact_number',
        string='Personal Phone Number')
    
    onboarding_email = fields.Char(
        related='employee_id.personal_email',
        string='Personal Email')
    

    # ── Employee Offboarding Information ───────────────────────────────
    # Source: hr.employee
    offboarding_employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        tracking=True,
    )

    offboarding_department_id = fields.Many2one(
        related='offboarding_employee_id.department_id',
        string='Department',
        readonly=True,
    )

    offboarding_position_id = fields.Many2one(
        related='offboarding_employee_id.job_id',
        string='Job Position',
        readonly=True,
    )

    offboarding_job_title = fields.Char(
        related='offboarding_employee_id.job_title',
        string='Job Title',
        readonly=True,
    )
    offboarding_role_band = fields.Char(
        string='Role Band',
        readonly=True,
    )
    # related='offboarding_employee_id.role_band',

    offboarding_employee_code = fields.Char(
        string='Employee Code',
        readonly=True,
    )
    # related='offboarding_employee_id.employee_code',

    offboarding_manager_id = fields.Many2one(
        related='offboarding_employee_id.parent_id',
        string='Manager',
        readonly=True,
    )

    offboarding_company_id = fields.Many2one(
        related='offboarding_employee_id.company_id',
        string='Company',
        readonly=True,
    )
    offboarding_category = fields.Char(
        string='EMP Category',
    )
    offboarding_emp_skill_category = fields.Char(
        string='EMP Skill Category',
    )
    offboarding_phone_number = fields.Char(
        related='offboarding_employee_id.private_phone',
        string='Personal Phone Number')

    offboarding_email = fields.Char(
            related='offboarding_employee_id.private_email',
            string='Personal Email')
    
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
        """Load tasks and switch between onboarding/offboarding employee."""
        self.task_line_ids = [(5, 0, 0)]

        if self.request_type_id and self.request_type_id.task_ids:
            lines = []
            for task in self.request_type_id.task_ids:
                lines.append((0, 0, {
                    'task': task.task,
                    'performed_by': (
                        task.performed_by.id
                        if task.performed_by else False
                    ),
                    'sequence': task.sequence,
                    'status': 'incomplete',
                    'review': 'pending',
                }))
            self.task_line_ids = lines

        if not self.request_type_id:
            self.employee_id = False
            self.offboarding_employee_id = False
            return

        if self.request_type_id.employee_model == 'hr.bxi.employee':
            self.offboarding_employee_id = False
        else:
            self.employee_id = False

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        """Onboarding employee is selected from hr.bxi.employee."""
        if self.employee_id:
            self.onboarding_company_id = (
                getattr(self.employee_id, 'onboarding_company_id', False)
                or self.env.company
            )
            self.work_email = (
                getattr(self.employee_id, 'work_email', False)
                or getattr(self.employee_id, 'personal_email', False)
                or False
            )
            self.work_phone = (
                getattr(self.employee_id, 'work_phone', False)
                or getattr(self.employee_id, 'contact_number', False)
                or False
            )

    @api.onchange('offboarding_employee_id')
    def _onchange_offboarding_employee_id(self):
        """Offboarding employee is selected from hr.employee."""
        if self.offboarding_employee_id:
            self.offboarding_company_id = (
                getattr(self.offboarding_employee_id, 'offboarding_company_id', False)
                or self.env.company
            )
            self.work_email = (
                getattr(self.offboarding_employee_id, 'work_email', False)
                or getattr(self.offboarding_employee_id, 'private_email', False)
                or False
            )
            self.work_phone = (
                getattr(self.offboarding_employee_id, 'work_phone', False)
                or getattr(self.offboarding_employee_id, 'mobile_phone', False)
                or False
            )

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

                selected_employee = (
                    rec.employee_id
                    if rec.request_type_id.employee_model == 'hr.bxi.employee'
                    else rec.offboarding_employee_id
                )

                subject = _("New Tasks Assigned: %s - %s (%s)") % (
                    rec.request_type_id.name or _('Request'),
                    selected_employee.name if selected_employee else '',
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
                        <p>A new <strong>{rec.request_type_id.name or ''}</strong> request (Ref: <strong>{rec.name or ''}</strong>) has been raised for employee <strong>{selected_employee.name if selected_employee else ''}</strong>.</p>
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
