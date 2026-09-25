# -*- coding: utf-8 -*-
from odoo import models, fields


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    compliance_case_count = fields.Integer(
        compute='_compute_compliance_case_count',
        groups='bxi_hr_policy.group_policy_cpo',
    )

    def _compute_compliance_case_count(self):
        Case = self.env['antitrust.case'].sudo()
        for employee in self:
            employee.compliance_case_count = Case.search_count([('employee_ids', 'in', employee.id)])

    def action_view_compliance_cases(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Compliance Cases'),
            'res_model': 'antitrust.case',
            'view_mode': 'list,form',
            'domain': [('employee_ids', 'in', self.id)],
            'context': {'default_employee_ids': [(6, 0, self.ids)]},
        }
