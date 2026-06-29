# -*- coding: utf-8 -*-
from odoo import fields, models


class HrContributionRegister(models.Model):
    """Create a new model for adding fields."""
    _name = 'hr.contribution.register'
    _description = 'Contribution Register'

    company_id = fields.Many2one('res.company',string='Company',
                                 required=True,default=lambda self: self.env.company.id)
    partner_id = fields.Many2one('res.partner', string='Partner',
                                 help="Choose Partner for Register")
    name = fields.Char(required=True, string="Name",
                       help="Contribution Register Name")
    register_line_ids = fields.One2many('hr.payslip.line',
                                        'register_id',
                                        string='Register Line',
                                        readonly=True,
                                        help="Choose Payslip line")
    note = fields.Text(string='Description',
                       help="Set Description for Register")
