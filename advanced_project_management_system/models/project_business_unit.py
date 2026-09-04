# -*- coding: utf-8 -*-
#############################################################################
#    Cybrosys Technologies Pvt. Ltd.
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    License LGPL-3.
#############################################################################
from odoo import fields, models


class ProjectBusinessUnit(models.Model):
    """Business unit a project is governed by."""
    _name = 'project.business.unit'
    _description = 'Project Business Unit'
    _order = 'sequence, name'

    name = fields.Char(string='Business Unit', required=True,
                       help="Name of the business unit.")
    code = fields.Char(string='Code', help="Short code of the business unit.")
    sequence = fields.Integer(string='Sequence', default=10)
    manager_id = fields.Many2one('res.users', string='Head',
                                 help="User heading this business unit.")
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)
    active = fields.Boolean(string='Active', default=True)

    _name_uniq = models.Constraint('unique(name, company_id)',
                                   'A business unit name must be unique.')
