# -*- coding: utf-8 -*-
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services.client_api import HdfcApiClient
from ..services.client_base import HdfcClientError
from ..services.client_mock import HdfcMockClient

IFSC_RE = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')
ACCOUNT_RE = re.compile(r'^\d{9,18}$')


class HdfcBankConfig(models.Model):
    _name = 'hdfc.bank.config'
    _description = 'HDFC Bank Payroll Configuration'
    _inherit = ['mail.thread']
    _check_company_auto = True
    _order = 'company_id, id'

    name = fields.Char(required=True, default='HDFC Payroll', tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', required=True, index=True, tracking=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related='company_id.currency_id')
    environment = fields.Selection(
        [('mock', 'Mock (no bank calls)'), ('uat', 'UAT'), ('prod', 'Production')],
        required=True, default='mock', tracking=True,
    )
    base_url = fields.Char(string='API Base URL', tracking=True)

    # --- Identity issued by HDFC ---
    corporate_id = fields.Char(string='Corporate ID', tracking=True)
    hdfc_user_id = fields.Char(string='HDFC User ID', tracking=True)
    aggregator_id = fields.Char(string='Aggregator ID', tracking=True)
    client_id = fields.Char(string='Client ID', tracking=True)

    # --- Secrets ---
    client_secret = fields.Char(groups='base.group_system', copy=False)
    api_key = fields.Char(string='API Key', groups='base.group_system', copy=False)
    client_private_key = fields.Binary(attachment=True, groups='base.group_system', copy=False)
    client_private_key_name = fields.Char(groups='base.group_system', copy=False)
    client_certificate = fields.Binary(attachment=True, groups='base.group_system', copy=False)
    client_certificate_name = fields.Char(groups='base.group_system', copy=False)
    bank_public_certificate = fields.Binary(attachment=True, groups='base.group_system', copy=False)
    bank_public_certificate_name = fields.Char(groups='base.group_system', copy=False)

    # --- Debit account ---
    debit_account_number = fields.Char(tracking=True)
    debit_ifsc = fields.Char(string='Debit IFSC', tracking=True)
    debit_account_name = fields.Char(tracking=True)

    # --- Payment rules ---
    rtgs_threshold = fields.Monetary(
        string='RTGS Threshold', default=200000.0,
        help='Payments to other banks at or above this amount are sent by RTGS, below it by NEFT (or IMPS).',
    )
    allow_imps = fields.Boolean(string='Use IMPS below RTGS threshold')
    max_lines_per_batch = fields.Integer(default=1000)
    narration_template = fields.Char(
        default='Salary {period}',
        help='Narration sent to the bank. Placeholders: {period} (e.g. Sep 2026), {employee}, {payslip}.',
    )
    otp_validity_minutes = fields.Integer(string='OTP Validity (minutes)', default=10)
    otp_max_attempts = fields.Integer(string='OTP Attempts', default=3)
    require_trusted_accounts = fields.Boolean(
        default=True,
        help='Only pay employee bank accounts marked as trusted (Send Money enabled).',
    )
    log_retention_days = fields.Integer(default=180)

    # --- Accounting ---
    journal_id = fields.Many2one(
        'account.journal', string='Bank Journal', check_company=True, tracking=True,
        domain="[('type', '=', 'bank')]",
        help='Journal of the HDFC account the salaries are debited from.',
    )
    salary_entry_mode = fields.Selection(
        [('payable', 'Salary Payable'), ('expense', 'Salary Expense')],
        string='Debit Salary To', required=True, default='payable', tracking=True,
        help='Salary Payable: the monthly accrual is posted separately and this payment settles it.\n'
             'Salary Expense: this payment is the only salary entry.',
    )
    salary_payable_account_id = fields.Many2one(
        'account.account', check_company=True, tracking=True,
        domain="[('account_type', 'in', ('liability_current', 'liability_payable'))]",
    )
    salary_expense_account_id = fields.Many2one(
        'account.account', check_company=True, tracking=True,
        domain="[('account_type', 'in', ('expense', 'expense_direct_cost'))]",
    )
    credit_account_id = fields.Many2one(
        'account.account', string='Credit Account', check_company=True, tracking=True,
        compute='_compute_credit_account_id', store=True, readonly=False,
        help='Outstanding payments account of the bank journal, reconciled with the bank statement.',
    )
    auto_post = fields.Boolean(string='Post Entries Automatically', default=True)

    _company_active_uniq = models.UniqueIndex(
        '(company_id) WHERE active IS TRUE',
        'Only one active HDFC configuration is allowed per company.',
    )

    @api.depends('journal_id')
    def _compute_credit_account_id(self):
        for config in self:
            journal = config.journal_id
            if not journal:
                config.credit_account_id = config.credit_account_id
                continue
            account = journal.outbound_payment_method_line_ids.payment_account_id[:1]
            if not account:
                account = self.env['account.chart.template'].with_company(config.company_id).ref(
                    'account_journal_payment_credit_account_id', raise_if_not_found=False)
            config.credit_account_id = account or journal.default_account_id

    @api.constrains('debit_ifsc', 'debit_account_number')
    def _check_debit_account(self):
        for config in self:
            if config.debit_ifsc and not IFSC_RE.match(config.debit_ifsc):
                raise ValidationError(_('The debit IFSC "%s" is not valid.', config.debit_ifsc))
            if config.debit_account_number and not ACCOUNT_RE.match(config.debit_account_number):
                raise ValidationError(_('The debit account number must contain 9 to 18 digits.'))

    @api.constrains('otp_validity_minutes', 'otp_max_attempts', 'max_lines_per_batch', 'rtgs_threshold')
    def _check_limits(self):
        for config in self:
            if config.otp_validity_minutes <= 0 or config.otp_max_attempts <= 0 or config.max_lines_per_batch <= 0:
                raise ValidationError(_('OTP validity, OTP attempts and batch size must be positive.'))
            if config.rtgs_threshold < 0:
                raise ValidationError(_('The RTGS threshold cannot be negative.'))

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------

    @api.model
    def _get_for_company(self, company):
        return self.sudo().search([('company_id', '=', company.id), ('active', '=', True)], limit=1)

    def _get_salary_debit_account(self):
        self.ensure_one()
        if self.salary_entry_mode == 'expense':
            return self.salary_expense_account_id
        return self.salary_payable_account_id

    def _get_setup_errors(self):
        """:return: list of messages explaining why this configuration cannot pay yet."""
        self.ensure_one()
        errors = []
        if self.company_id.currency_id.name != 'INR':
            errors.append(_('Company %s does not use INR.', self.company_id.name))
        if not (self.debit_account_number and self.debit_ifsc):
            errors.append(_('The debit account number and IFSC are required.'))
        if self.environment != 'mock' and not (self.base_url and self.corporate_id):
            errors.append(_('The API base URL and corporate ID are required outside mock mode.'))
        if not self.journal_id:
            errors.append(_('The bank journal is required.'))
        if not self._get_salary_debit_account():
            errors.append(_('The %s account is required.',
                            dict(self._fields['salary_entry_mode'].selection)[self.salary_entry_mode]))
        if not self.credit_account_id:
            errors.append(_('The credit (outstanding payments) account is required.'))
        return errors

    def _get_txn_type(self, ifsc, amount):
        self.ensure_one()
        if ifsc.startswith('HDFC'):
            return 'internal'
        if self.company_id.currency_id.compare_amounts(amount, self.rtgs_threshold) >= 0:
            return 'rtgs'
        return 'imps' if self.allow_imps else 'neft'

    def _get_client(self):
        self.ensure_one()
        if self.environment == 'mock':
            return HdfcMockClient(self.sudo())
        return HdfcApiClient(self.sudo())

    def action_test_connection(self):
        self.ensure_one()
        try:
            result = self._get_client().test_connection()
        except HdfcClientError as exc:
            raise UserError(str(exc)) from exc
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'type': 'success', 'message': result.get('message'), 'sticky': False},
        }
