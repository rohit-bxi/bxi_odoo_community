# -*- coding: utf-8 -*-
from odoo import fields, models


class HrRuleInput(models.Model):
    """Create new model for adding some fields"""
    _name = 'hr.rule.input'
    _description = 'Salary Rule Input'

    name = fields.Char(string='Description', required=True,
                       help="Description for Salary Rule Input")
    code = fields.Char(required=True, string="Code",
                       help="The code that can be used in the salary rules")
    input_id = fields.Many2one('hr.salary.rule',
                               string='Salary Rule Input',
                               required=True, help="Choose Salary Rule")
