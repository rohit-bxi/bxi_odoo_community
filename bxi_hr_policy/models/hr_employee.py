# -*- coding: utf-8 -*-
from odoo import models, api


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        self.env['hr.policy.acknowledgement']._sync_employees(employees.filtered('active'))
        return employees

    def write(self, vals):
        res = super().write(vals)
        if 'active' in vals and not vals['active']:
            # Leavers: nothing left to acknowledge.
            self.env['hr.policy.acknowledgement'].sudo().search([
                ('employee_id', 'in', self.ids), ('state', 'in', ('pending', 'overdue')),
            ])._cancel()
        elif vals.get('active') or vals.get('user_id'):
            # Rehired employees, or employees who just got a user account.
            self.env['hr.policy.acknowledgement']._sync_employees(self.filtered('active'))
        return res
