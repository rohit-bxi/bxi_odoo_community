from odoo import models, fields, api


class EmployeeOnboardingOffboarding(models.Model):
    _inherit = 'employee.onboarding.offboarding'

    certification_agreement_ids = fields.Many2many(
        'bxi.service.agreement',
        string='Certification Service Agreements',
        compute='_compute_certification_dues',
    )
    certification_voucher_ids = fields.Many2many(
        'bxi.certification.voucher',
        string='Unrecovered Certification Vouchers',
        compute='_compute_certification_dues',
    )
    certification_due_amount = fields.Monetary(
        string='Certification Dues',
        compute='_compute_certification_dues',
        currency_field='certification_currency_id',
    )
    certification_currency_id = fields.Many2one(
        'res.currency',
        compute='_compute_certification_dues',
    )

    @api.depends('offboarding_employee_id', 'effective_date')
    def _compute_certification_dues(self):
        Agreement = self.env['bxi.service.agreement'].sudo()
        Voucher = self.env['bxi.certification.voucher'].sudo()
        for rec in self:
            employee = rec.offboarding_employee_id
            leaving_date = rec.effective_date or employee.sudo().date_of_leaving
            agreements = Agreement.search([
                ('employee_id', '=', employee.id), ('state', '=', 'active'),
            ]).filtered(lambda a: a._is_due_on(leaving_date)) if employee else Agreement
            vouchers = Voucher.search([
                ('employee_id', '=', employee.id), ('state', '=', 'expired'),
            ]) if employee else Voucher
            rec.certification_agreement_ids = agreements
            rec.certification_voucher_ids = vouchers
            rec.certification_due_amount = sum(agreements.mapped('amount')) + sum(vouchers.mapped('cost'))
            rec.certification_currency_id = self.env.company.currency_id
