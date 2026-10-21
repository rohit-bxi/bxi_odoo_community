# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    milestone_hr_email = fields.Char(
        string='HR Email for Milestones',
        default='hrsupport@bxitech.com',
        help='Copied on job anniversary emails and notified of probation reviews.',
    )
