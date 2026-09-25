from odoo import api, fields, models
from odoo.exceptions import UserError


class BxiSalaryAdvanceDisburseWizard(models.TransientModel):
    _name = 'bxi.salary.advance.disburse.wizard'
    _description = 'Disburse Salary Advance'

    advance_id = fields.Many2one('bxi.salary.advance', string='Salary Advance', required=True)
    company_id = fields.Many2one(related='advance_id.company_id')
    currency_id = fields.Many2one(related='advance_id.currency_id')
    amount = fields.Monetary(related='advance_id.amount_approved', string='Amount')
    category = fields.Selection(related='advance_id.category')
    vendor_partner_id = fields.Many2one(related='advance_id.vendor_partner_id')
    date = fields.Date(string='Disbursement Date', required=True, default=fields.Date.context_today)
    reference = fields.Char(string='Payment Reference', help="Bank transfer reference (UTR) or cheque number.")
    create_entry = fields.Boolean(
        string='Post Journal Entry', compute='_compute_create_entry', store=True, readonly=False,
        help="Debit the Employee Advance account and credit the bank (or the third-party vendor for housing "
             "advances). Leave unticked when the payment is booked elsewhere.")
    journal_id = fields.Many2one(
        'account.journal', string='Journal', check_company=True,
        compute='_compute_create_entry', store=True, readonly=False,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]")

    @api.depends('advance_id')
    def _compute_create_entry(self):
        for wizard in self:
            company = wizard.advance_id.company_id
            wizard.create_entry = bool(company.sa_advance_account_id)
            wizard.journal_id = company.sa_disbursement_journal_id

    def action_disburse(self):
        self.ensure_one()
        if not self.advance_id.can_disburse:
            raise UserError(self.env._("Only Finance can disburse approved advances."))
        if self.create_entry and not self.journal_id:
            raise UserError(self.env._("Select the journal the advance is paid from."))
        self.advance_id._action_disburse(
            self.date, reference=self.reference, journal=self.journal_id if self.create_entry else False)
        return {'type': 'ir.actions.act_window_close'}
