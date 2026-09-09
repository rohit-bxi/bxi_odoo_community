# -*- coding: utf-8 -*-

from odoo import models, fields, api


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    offboarding_ids = fields.One2many(
        'employee.onboarding.offboarding',
        'offboarding_employee_id',
        string='Offboarding Requests',
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

    @api.depends('offboarding_ids')
    def _compute_onboarding_count(self):
        read_group_result = self.env['employee.onboarding.offboarding']._read_group(
            [('offboarding_employee_id', 'in', self.ids)],
            ['offboarding_employee_id'],
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


class HrBxiEmployee(models.Model):
    _name = 'hr.bxi.employee'
    _description = 'BXI Employee'
    _rec_name = 'name'
    _order = 'name asc'

    name = fields.Char(
        string='Full Name',
        required=True,
        index=True,
    )
    contact_number = fields.Char(
        string='Contact Number',
    )
    personal_email = fields.Char(
        string='Personal Email',
    )
    job_title = fields.Char(
        string='Job Title',
    )
    job_id = fields.Many2one(
        'hr.job',
        string='Job Position')
    company_id = fields.Many2one(
        'res.company',
        string='Organization / Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        index=True,
    )

    reporting_manager_id = fields.Many2one(
        'hr.employee',
        string='Reporting Manager',
        store=True,
    )

    work_location_id = fields.Many2one(
        'hr.work.location',
        string='Work Location',
        index=True,
    )

    date_of_joining = fields.Date(
        string='Date of Joining',
        index=True,
    )
