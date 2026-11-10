# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class TimesheetCategory(models.Model):
    """
    Level 1 (L1) Category for Timesheet tracking.
    """
    _name = 'timesheet.category'
    _description = 'Timesheet Category (L1)'
    _order = 'sequence, name'

    name = fields.Char(string='Category Name', required=True, translate=True)
    code = fields.Char(string='Code', index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)
    activity_ids = fields.One2many('timesheet.activity', 'category_id', string='Activities (L2)')

    is_crm = fields.Boolean(
        string='Dynamic CRM Leads/Opportunities',
        default=False,
        help='If checked, L2 activities are dynamically fetched from CRM leads/opportunities.'
    )
    is_project = fields.Boolean(
        string='Dynamic Project Allocations',
        default=False,
        help='If checked, L2 activities are dynamically fetched from assigned project allocations.'
    )


class TimesheetActivity(models.Model):
    """
    Level 2 (L2) Activity for Timesheet tracking.
    Belongs to an L1 category.
    """
    _name = 'timesheet.activity'
    _description = 'Timesheet Activity (L2)'
    _order = 'sequence, name'

    name = fields.Char(string='Activity Name', required=True, translate=True)
    category_id = fields.Many2one(
        'timesheet.category',
        string='Category (L1)',
        required=True,
        ondelete='cascade',
        index=True
    )
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(
        string='Active',
        default=True,
        help='Inactive activities cannot be selected.'
    )

    _sql_constraints = [
        ('category_activity_unique', 'unique(category_id, name)', 'Activity name must be unique per category!')
    ]


class TimesheetDepartmentCategory(models.Model):
    """
    Links HR Department (hr.department) with Timesheet Category L1 (timesheet.category)
    so employees only see categories linked to their department when logging timesheets.
    """
    _name = 'timesheet.department.category'
    _description = 'Department Category Linking'
    _order = 'company_id, department_id, category_id'
    _rec_name = 'display_name'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        required=True,
        ondelete='cascade',
        index=True,
        domain="[('company_id', '=', company_id)]",
    )
    category_id = fields.Many2one(
        'timesheet.category',
        string='Category (L1)',
        required=True,
        ondelete='cascade',
        index=True,
        domain=[('active', '=', True)],
    )
    active = fields.Boolean(string='Active', default=True)

    _unique_department_category = models.Constraint(
        'UNIQUE(department_id, category_id)',
        'This Department and Category (L1) link already exists.',
    )

    @api.onchange('company_id')
    def _onchange_company_id(self):
        if self.department_id and (not self.company_id or self.department_id.company_id != self.company_id):
            self.department_id = False

    @api.constrains('company_id', 'department_id')
    def _check_company_department(self):
        for rec in self:
            if rec.department_id and rec.company_id and rec.department_id.company_id != rec.company_id:
                raise ValidationError(_(
                    "The selected department '%s' does not belong to company '%s'."
                ) % (rec.department_id.name, rec.company_id.name))

    @api.depends('department_id', 'category_id')
    def _compute_display_name(self):
        for rec in self:
            dept = rec.department_id.name or ''
            cat = rec.category_id.name or ''
            if dept and cat:
                rec.display_name = f"{dept} - {cat}"
            else:
                rec.display_name = dept or cat or ''
