from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.bxi_salary_advance.models.salary_advance import HR_GROUP


class BxiSalaryAdvanceHostRecoveryWizard(models.TransientModel):
    _name = 'bxi.salary.advance.host.recovery.wizard'
    _description = 'Record Salary Advance Recovered at the Host Location'

    advance_id = fields.Many2one('bxi.salary.advance', string='Salary Advance', required=True)
    company_id = fields.Many2one(related='advance_id.company_id')
    currency_id = fields.Many2one(related='advance_id.currency_id')
    amount = fields.Monetary(string='Amount Recovered', compute='_compute_amount', currency_field='currency_id')
    date = fields.Date(string='Recovered On', required=True, default=fields.Date.context_today)
    reference = fields.Char(string='Reference', required=True,
                            help="Host payslip, payment or inter-company settlement reference.")
    post_entry = fields.Boolean(
        string='Post Journal Entry',
        help="Credit the Employee Advance account against the account below (e.g. the inter-company "
             "receivable from the host entity).")
    counterpart_account_id = fields.Many2one(
        'account.account', string='Counterpart Account', check_company=True)

    @api.depends('advance_id')
    def _compute_amount(self):
        for wizard in self:
            pending = wizard.advance_id.sudo().installment_ids.filtered(lambda inst: inst.state == 'pending')
            wizard.amount = sum(pending.mapped('amount'))

    def action_confirm(self):
        self.ensure_one()
        advance = self.advance_id.sudo()
        if not advance.recover_at_host or not self.env.user.has_group(HR_GROUP):
            raise UserError(self.env._("Only HR can record the recovery of a balance due at the host location."))
        pending = advance.installment_ids.filtered(lambda inst: inst.state == 'pending')
        move = self._post_entry(advance) if self.post_entry else self.env['account.move']
        for inst in pending:
            inst.write({
                'state': 'deducted',
                'amount_recovered': inst.amount,
                'date_recovered': self.date,
                'move_id': move.id,
            })
        advance.message_post(body=self.env._(
            "%(amount)s recovered by the host payroll on %(date)s (reference: %(reference)s).",
            amount=advance.currency_id.format(self.amount), date=self.date, reference=self.reference))
        advance._check_closed()
        return {'type': 'ir.actions.act_window_close'}

    def _post_entry(self, advance):
        company = advance.company_id
        if not (self.counterpart_account_id and company.sa_advance_account_id and company.sa_recovery_journal_id):
            raise UserError(self.env._(
                "Select the counterpart account; the Employee Advance Account and the Recovery Journal must be "
                "set in the Salary Advance settings."))
        label = self.env._("Salary advance %(name)s - recovered at host location (%(reference)s)",
                           name=advance.name, reference=self.reference)
        partner = advance._get_employee_partner()
        move = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': company.sa_recovery_journal_id.id,
            'date': self.date,
            'ref': label,
            'company_id': company.id,
            'line_ids': [
                Command.create({
                    'name': label, 'account_id': self.counterpart_account_id.id,
                    'partner_id': partner.id, 'debit': self.amount, 'credit': 0.0,
                }),
                Command.create({
                    'name': label, 'account_id': company.sa_advance_account_id.id,
                    'partner_id': partner.id, 'debit': 0.0, 'credit': self.amount,
                }),
            ],
        })
        move.action_post()
        return move
