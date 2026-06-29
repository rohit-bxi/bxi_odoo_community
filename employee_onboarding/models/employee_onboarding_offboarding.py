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
                if 'offboarding' in request_type_name.lower():
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
