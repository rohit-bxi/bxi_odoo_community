# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class EmployeeResignation(models.Model):
    _name = 'employee.resignation'
    _description = 'Employee Resignation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'resignation_date desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )

    # ── Employee Information ─────────────────────────────────────────────
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        tracking=True,
        default=lambda self: self.env.user.employee_id,
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
    job_id = fields.Many2one(
        'hr.job',
        string='Job Position',
        readonly=True,
    )
    manager_id = fields.Many2one(
        'hr.employee',
        string='Manager',
        readonly=True,
    )
    emp_date_of_joining = fields.Date(
        string='Date of Joining',
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        readonly=True,
        default=lambda self: self.env.company,
    )

    # ── Resignation Details ──────────────────────────────────────────────
    resignation_date = fields.Date(
        string='Resignation Date',
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    last_working_day = fields.Date(
        string='Requested Last Working Day',
        required=True,
        tracking=True,
    )
    approved_last_working_day = fields.Date(
        string='Approved Last Working Day',
        tracking=True,
    )
    reason = fields.Selection(
        [
            ('better_opportunity', 'Better Opportunity / Career Growth'),
            ('personal', 'Personal Reasons'),
            ('health', 'Health Issues'),
            ('relocation', 'Relocation / Family reasons'),
            ('education', 'Higher Education'),
            ('other', 'Other'),
        ],
        string='Reason for Resignation',
        required=True,
        tracking=True,
    )
    resignation_body = fields.Html(
        string='Resignation Letter',
        required=True,
    )
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'employee_resignation_attachment_rel',
        'resignation_id',
        'attachment_id',
        string='Attachments',
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
    )

    # ── Constraints & Validation ─────────────────────────────────────────
    @api.constrains('resignation_date', 'last_working_day')
    def _check_dates(self):
        for rec in self:
            if rec.resignation_date and rec.last_working_day and rec.last_working_day < rec.resignation_date:
                raise ValidationError(_("The Requested Last Working Day cannot be earlier than the Resignation Date."))

    # ── Onchange ─────────────────────────────────────────────────────────
    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            emp = self.employee_id
            self.employee_code = getattr(emp, 'employee_code', False)
            self.department_id = emp.department_id
            self.job_id = emp.job_id
            self.manager_id = emp.parent_id
            self.company_id = emp.company_id
            self.emp_date_of_joining = getattr(emp, 'emp_date_of_joining', False)
        else:
            self.employee_code = False
            self.department_id = False
            self.job_id = False
            self.manager_id = False
            self.company_id = self.env.company
            self.emp_date_of_joining = False

    # ── Sequence ─────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'employee.resignation.sequence'
                ) or _('New')
            
            # Auto-fill employee details if not already provided
            if vals.get('employee_id'):
                emp = self.env['hr.employee'].browse(vals['employee_id'])
                if emp:
                    vals['employee_code'] = getattr(emp, 'employee_code', False)
                    vals['department_id'] = emp.department_id.id if emp.department_id else False
                    vals['job_id'] = emp.job_id.id if emp.job_id else False
                    vals['manager_id'] = emp.parent_id.id if emp.parent_id else False
                    vals['company_id'] = emp.company_id.id if emp.company_id else self.env.company.id
                    vals['emp_date_of_joining'] = getattr(emp, 'emp_date_of_joining', False)
        return super().create(vals_list)

    def write(self, vals):
        if 'employee_id' in vals:
            if vals.get('employee_id'):
                emp = self.env['hr.employee'].browse(vals['employee_id'])
                if emp:
                    vals['employee_code'] = getattr(emp, 'employee_code', False)
                    vals['department_id'] = emp.department_id.id if emp.department_id else False
                    vals['job_id'] = emp.job_id.id if emp.job_id else False
                    vals['manager_id'] = emp.parent_id.id if emp.parent_id else False
                    vals['company_id'] = emp.company_id.id if emp.company_id else False
                    vals['emp_date_of_joining'] = getattr(emp, 'emp_date_of_joining', False)
            else:
                vals['employee_code'] = False
                vals['department_id'] = False
                vals['job_id'] = False
                vals['manager_id'] = False
                vals['company_id'] = False
                vals['emp_date_of_joining'] = False
        return super().write(vals)

    # ── State Actions ────────────────────────────────────────────────────
    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                continue
            rec.state = 'submitted'

    def action_approve(self):
        for rec in self:
            if rec.state != 'submitted':
                continue
            rec.state = 'approved'
            # Set approved last working day to requested last working day if not set
            if not rec.approved_last_working_day:
                rec.approved_last_working_day = rec.last_working_day

    def action_reject(self):
        for rec in self:
            if rec.state != 'submitted':
                continue
            rec.state = 'rejected'

    def action_cancel(self):
        for rec in self:
            if rec.state not in ('draft', 'submitted'):
                continue
            rec.state = 'cancelled'

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ('rejected', 'cancelled'):
                continue
            rec.state = 'draft'
