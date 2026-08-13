# -*- coding: utf-8 -*-

from odoo import models, fields


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    l10n_in_relationship = fields.Char(string="Emergency Relationship")
    is_non_resident = fields.Boolean(string="Non-Resident")
    disabled = fields.Boolean(string="Disabled")
    legal_name = fields.Char(string="Legal Name")


class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    l10n_in_relationship = fields.Char(related='employee_id.l10n_in_relationship')
    is_non_resident = fields.Boolean(related='employee_id.is_non_resident')
    disabled = fields.Boolean(related='employee_id.disabled')
    legal_name = fields.Char(related='employee_id.legal_name')
