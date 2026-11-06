# -*- coding: utf-8 -*-
from odoo import models, fields, api

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
