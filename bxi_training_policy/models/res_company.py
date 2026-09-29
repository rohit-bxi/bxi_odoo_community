from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    trn_hr_user_id = fields.Many2one(
        'res.users', string='Training HR Responsible',
        help="Receives the nominations and approves claims as HR. When empty, every Training HR Officer of the "
             "company is notified and can approve.")
    trn_es_user_id = fields.Many2one(
        'res.users', string='Training Employee Services Responsible',
        help="Gives the final approval of the claims. When empty, any Employee Services user can approve.")
    trn_finance_user_id = fields.Many2one(
        'res.users', string='Training Finance Responsible',
        help="Receives the approved claims to pay. When empty, every Training Finance user is notified.")
    trn_policy_id = fields.Many2one(
        'hr.company.policy', string='Training Policy',
        help="When the policy requires acknowledgement, the employee must acknowledge it before the training "
             "starts.")
    trn_signatory_name = fields.Char(
        string='Authorised Signatory', help="Name printed on the service agreement for the company.")
    trn_accounting_mode = fields.Selection(
        [
            ('bonded', 'Keep as bonded cost until the service period is served'),
            ('expense', 'Expense immediately'),
        ],
        string='Training Cost Accounting', default='bonded', required=True)
    trn_advance_account_id = fields.Many2one(
        'account.account', string='Training Advance Account', check_company=True,
        help="Receivable debited when the advance is paid and credited when it is settled against the claim.")
    trn_bonded_account_id = fields.Many2one(
        'account.account', string='Bonded Training Cost Account', check_company=True,
        help="Asset holding the training cost while the service agreement runs (bonded mode).")
    trn_expense_account_id = fields.Many2one(
        'account.account', string='Training Expense Account', check_company=True)
    trn_recovery_account_id = fields.Many2one(
        'account.account', string='Payroll Recovery Debit Account', check_company=True,
        help="Account debited when a recovery is deducted from a payslip, usually Salary Payable.")
    trn_journal_id = fields.Many2one(
        'account.journal', string='Advance Payment Journal', check_company=True,
        domain="[('type', 'in', ('bank', 'cash'))]")
    trn_misc_journal_id = fields.Many2one(
        'account.journal', string='Training Miscellaneous Journal', check_company=True,
        domain="[('type', '=', 'general')]")
