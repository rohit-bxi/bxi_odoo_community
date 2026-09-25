from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    sa_hr_user_id = fields.Many2one(
        'res.users', string='Salary Advance HR Responsible',
        help="Receives the requests approved by Reporting Managers. When empty, every Salary Advance "
             "HR Officer of the company is notified.")
    sa_finance_user_id = fields.Many2one(
        'res.users', string='Salary Advance Finance Responsible',
        help="Receives the approved requests to disburse. When empty, every Salary Advance "
             "Finance user of the company is notified.")
    sa_geo_hr_head_id = fields.Many2one(
        'res.users', string='Geo HR Head (Onsite)',
        help="Approves exceptions to the Salary Advance Policy for onsite employees.")
    sa_advance_account_id = fields.Many2one(
        'account.account', string='Employee Advance Account', check_company=True,
        help="Receivable account debited when an advance is disbursed and credited as it is recovered.")
    sa_disbursement_journal_id = fields.Many2one(
        'account.journal', string='Disbursement Journal', check_company=True,
        domain="[('type', 'in', ('bank', 'cash'))]")
    sa_recovery_account_id = fields.Many2one(
        'account.account', string='Recovery Debit Account', check_company=True,
        help="Account debited when an instalment is deducted from a payslip, usually Salary Payable. "
             "When empty, no journal entry is posted for recoveries.")
    sa_recovery_journal_id = fields.Many2one(
        'account.journal', string='Recovery Journal', check_company=True,
        domain="[('type', '=', 'general')]")
    sa_policy_id = fields.Many2one(
        'hr.company.policy', string='Salary Advance Policy',
        help="Shown to employees when they apply. When the policy requires acknowledgement, the "
             "employee must acknowledge its current version before submitting a request.")
    sa_request_form = fields.Binary(string='Advance Request Form', attachment=True)
    sa_request_form_filename = fields.Char(string='Advance Request Form Filename')
