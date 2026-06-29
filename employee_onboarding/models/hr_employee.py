# -*- coding: utf-8 -*-

from odoo import models, fields, api


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    onboarding_ids = fields.One2many(
        'employee.onboarding.offboarding',
        'employee_id',
        string='Onboarding / Offboarding Requests'
    )
    onboarding_count = fields.Integer(
        string="Onboarding / Offboarding Count",
        compute="_compute_onboarding_count"
    )
    resignation_ids = fields.One2many(
        'employee.resignation',
        'employee_id',
        string='Resignation Requests'
    )
    resignation_count = fields.Integer(
        string="Resignation Count",
        compute="_compute_resignation_count"
    )

    @api.depends('onboarding_ids')
    def _compute_onboarding_count(self):
        read_group_result = self.env['employee.onboarding.offboarding']._read_group(
            [('employee_id', 'in', self.ids)],
            ['employee_id'],
            ['__count']
        )
        result = {employee.id: count for employee, count in read_group_result}
        for employee in self:
            employee.onboarding_count = result.get(employee.id, 0)

    @api.depends('resignation_ids')
    def _compute_resignation_count(self):
        read_group_result = self.env['employee.resignation']._read_group(
            [('employee_id', 'in', self.ids)],
            ['employee_id'],
            ['__count']
        )
        result = {employee.id: count for employee, count in read_group_result}
        for employee in self:
            employee.resignation_count = result.get(employee.id, 0)

    def action_view_onboarding_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Onboarding / Offboarding',
            'res_model': 'employee.onboarding.offboarding',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {
                'default_employee_id': self.id,
            },
            'target': 'current',
        }

    def action_view_resignation_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Resignations',
            'res_model': 'employee.resignation',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {
                'default_employee_id': self.id,
            },
            'target': 'current',
        }
