# -*- coding: utf-8 -*-
from odoo import _, api, fields, models

from ..services.masking import mask_account

ACTIVE_LINE_STATES = ('draft', 'submitted', 'processing', 'paid')
TERMINAL_LINE_STATES = ('paid', 'failed', 'returned', 'cancelled', 'reversed')


class HdfcPayoutLine(models.Model):
    _name = 'hdfc.payout.line'
    _description = 'HDFC Payout Line'
    _order = 'batch_id desc, id'
    _check_company_auto = True
    _rec_name = 'line_reference'

    batch_id = fields.Many2one('hdfc.payout.batch', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(related='batch_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    payslip_id = fields.Many2one('hr.payslip', required=True, index=True, ondelete='restrict', check_company=True)
    employee_id = fields.Many2one('hr.employee', required=True, index=True)
    partner_id = fields.Many2one('res.partner', string='Employee Contact')
    bank_account_id = fields.Many2one('res.partner.bank', required=True, ondelete='restrict')

    # Snapshot of the beneficiary at batch creation: later edits never change a submitted file.
    account_number = fields.Char(required=True)
    account_number_masked = fields.Char(string='Account', compute='_compute_account_number_masked')
    ifsc = fields.Char(string='IFSC', required=True)
    beneficiary_name = fields.Char(required=True)
    amount = fields.Monetary(required=True)
    narration = fields.Char()
    txn_type = fields.Selection(
        [('internal', 'HDFC Transfer'), ('neft', 'NEFT'), ('rtgs', 'RTGS'), ('imps', 'IMPS')],
        string='Mode', required=True,
    )
    line_reference = fields.Char(readonly=True, copy=False, index=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('processing', 'Processing'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('returned', 'Returned'),
        ('cancelled', 'Cancelled'),
        ('reversed', 'Reversed'),
    ], default='draft', required=True, index=True, copy=False)
    utr = fields.Char(string='UTR', copy=False, index=True)
    bank_txn_ref = fields.Char(string='Bank Transaction Ref', copy=False)
    value_date = fields.Date(copy=False)
    failure_reason = fields.Char(copy=False)
    move_id = fields.Many2one('account.move', string='Payment Entry', copy=False, readonly=True)
    reversal_move_id = fields.Many2one('account.move', string='Reversal Entry', copy=False, readonly=True)

    _line_reference_uniq = models.Constraint(
        'unique(line_reference)',
        'The HDFC line reference must be unique.',
    )
    _payslip_active_uniq = models.UniqueIndex(
        "(payslip_id, bank_account_id) WHERE state IN ('draft', 'submitted', 'processing', 'paid')",
        'This payslip is already included in an active HDFC payout for this bank account.',
    )
    _amount_positive = models.Constraint('CHECK(amount > 0)', 'Payout amounts must be positive.')

    @api.depends('account_number')
    def _compute_account_number_masked(self):
        for line in self:
            line.account_number_masked = mask_account(line.account_number)

    def _get_entry_label(self):
        self.ensure_one()
        label = _('Salary %(payslip)s - %(employee)s',
                  payslip=self.payslip_id.number or self.payslip_id.name or '',
                  employee=self.employee_id.name)
        if self.utr:
            label += ' - UTR %s' % self.utr
        return label
