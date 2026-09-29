from odoo import api, fields, models

from .training_agreement import BINDING_STATES
from .training_recovery import OPEN_STATES as RECOVERY_OPEN_STATES


class EmployeeOnboardingOffboarding(models.Model):
    _inherit = 'employee.onboarding.offboarding'

    training_agreement_ids = fields.Many2many(
        'bxi.training.agreement', string='Training Service Agreements', compute='_compute_training_dues')
    training_recovery_ids = fields.Many2many(
        'bxi.training.recovery', string='Training Recoveries', compute='_compute_training_dues')
    training_due_amount = fields.Monetary(
        string='Training Dues', compute='_compute_training_dues', currency_field='training_currency_id')
    training_currency_id = fields.Many2one('res.currency', compute='_compute_training_dues')

    @api.depends('offboarding_employee_id', 'effective_date')
    def _compute_training_dues(self):
        Agreement = self.env['bxi.training.agreement'].sudo()
        Recovery = self.env['bxi.training.recovery'].sudo()
        for rec in self:
            employee = rec.offboarding_employee_id
            leaving_date = rec.effective_date or employee.sudo().date_of_leaving
            agreements = Agreement.search([
                ('employee_id', '=', employee.id), ('state', 'in', BINDING_STATES),
            ]).filtered(lambda a: a._is_due_on(leaving_date)) if employee else Agreement
            recoveries = Recovery.search([
                ('employee_id', '=', employee.id), ('state', 'in', RECOVERY_OPEN_STATES),
            ]) if employee else Recovery
            rec.training_agreement_ids = agreements
            rec.training_recovery_ids = recoveries
            rec.training_due_amount = sum(agreements.mapped('amount')) + sum(recoveries.mapped('balance'))
            rec.training_currency_id = employee.company_id.currency_id or self.env.company.currency_id
