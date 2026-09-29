from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from .training_mixin import ADMIN_GROUP, FINANCE_GROUP, HR_GROUP

# Recoveries deducted from the payslips.
PAYROLL_STATES = ('payroll',)
# Recoveries still owed by the employee.
OPEN_STATES = ('pending', 'payroll', 'legal')


class BxiTrainingRecovery(models.Model):
    """Amount an employee owes back under the Training Policy."""
    _name = 'bxi.training.recovery'
    _description = 'Training Cost Recovery'
    _inherit = ['bxi.training.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default=lambda self: self.env._('New'),
    )
    state = fields.Selection(
        [
            ('pending', 'To Recover'),
            ('payroll', 'In Payroll'),
            ('legal', 'Legal Follow-up'),
            ('recovered', 'Recovered'),
            ('waived', 'Waived'),
        ],
        string='Status', default='payroll', required=True, tracking=True, copy=False, index=True,
    )
    reason = fields.Selection(
        [
            ('breach', 'Service agreement not served'),
            ('advance_excess', 'Unspent advance'),
            ('cancelled', 'Training cancelled after the advance'),
        ],
        string='Reason', required=True, readonly=True,
    )
    request_id = fields.Many2one('bxi.training.request', string='Training', readonly=True, index=True)
    agreement_id = fields.Many2one('bxi.training.agreement', string='Service Agreement', readonly=True, index=True)
    resignation_id = fields.Many2one('employee.resignation', string='Resignation', readonly=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, readonly=True, index=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        compute='_compute_company_id', store=True, readonly=False, precompute=True,
    )
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    amount_due = fields.Monetary(string='Amount Due', currency_field='currency_id', readonly=True, tracking=True)
    line_ids = fields.One2many('bxi.training.recovery.line', 'recovery_id', string='Recovery Lines')
    amount_recovered = fields.Monetary(
        string='Recovered', currency_field='currency_id', compute='_compute_amounts', store=True)
    balance = fields.Monetary(string='Balance', currency_field='currency_id', compute='_compute_amounts', store=True)
    payroll_month = fields.Date(
        string='Payroll Month', tracking=True,
        help="The balance is deducted from the payslip of this month (the last working month for the Full and "
             "Final Settlement).",
    )
    notice_date = fields.Date(string='Demand Notice Sent On', tracking=True)
    legal_case_ref = fields.Char(string='Legal Case Reference', tracking=True)
    waive_reason = fields.Text(string='Waiver Reason', readonly=True)
    notes = fields.Text(string='Notes')

    @api.depends('employee_id')
    def _compute_company_id(self):
        for rec in self:
            rec.company_id = rec.employee_id.sudo().company_id or rec.company_id or self.env.company

    @api.depends('amount_due', 'line_ids.amount')
    def _compute_amounts(self):
        for rec in self:
            rec.amount_recovered = sum(rec.line_ids.mapped('amount'))
            rec.balance = rec.currency_id.round(rec.amount_due - rec.amount_recovered)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', self.env._('New')) == self.env._('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.training.recovery') or self.env._('New')
        return super().create(vals_list)

    # ── Helpers ──────────────────────────────────────────────────────────
    def _check_hr_or_finance(self):
        user = self.env.user
        if not self.env.su and not (user.has_group(HR_GROUP) or user.has_group(FINANCE_GROUP)):
            raise AccessError(self.env._("Only HR or Finance can manage training recoveries."))

    def _get_credit_account(self):
        """Account credited when the amount comes back."""
        self.ensure_one()
        if self.reason in ('advance_excess', 'cancelled'):
            return self.company_id.trn_advance_account_id
        return self._get_cost_credit_account()

    def _notify_created(self):
        for rec in self:
            reason = dict(rec._fields['reason']._description_selection(rec.env)).get(rec.reason)
            month = rec.payroll_month.strftime('%B %Y') if rec.payroll_month else ''
            rec._notify_employee(self.env._(
                "%(amount)s is to be paid back to the company (%(reason)s). It will be deducted from the payroll "
                "of %(month)s.", amount=rec.currency_id.format(rec.amount_due), reason=reason, month=month))
            rec._notify_group(rec.company_id.sudo().trn_hr_user_id, HR_GROUP,
                              self.env._("Training recovery: %(employee)s", employee=rec.employee_id.name),
                              self.env._("%(amount)s - %(reason)s", amount=rec.currency_id.format(rec.amount_due),
                                         reason=reason))

    def _check_closed(self):
        for rec in self.sudo().filtered(lambda r: r.state in OPEN_STATES):
            if rec.currency_id.compare_amounts(rec.balance, 0) <= 0:
                rec.state = 'recovered'
                rec.agreement_id._on_recovery_closed('recovered')
                rec._notify_employee(self.env._("%(name)s has been fully recovered.", name=rec.name))

    def _reopen(self):
        for rec in self.sudo().filtered(lambda r: r.state == 'recovered'):
            rec.state = 'payroll' if rec.payroll_month else 'pending'
            if rec.agreement_id.state == 'recovered':
                rec.agreement_id.state = 'breached'

    # ── Actions ──────────────────────────────────────────────────────────
    def action_send_to_payroll(self):
        self._check_hr_or_finance()
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.state not in ('pending', 'legal'):
                raise UserError(self.env._("Only recoveries to recover can be sent to payroll."))
            rec.write({'state': 'payroll', 'payroll_month': rec.payroll_month or today.replace(day=1)})

    def action_mark_legal(self):
        self._check_hr_or_finance()
        for rec in self:
            if rec.state not in ('pending', 'payroll'):
                raise UserError(self.env._("Only open recoveries can be followed up legally."))
        self.write({'state': 'legal'})

    def action_print_demand_notice(self):
        self.ensure_one()
        self._check_hr_or_finance()
        if not self.notice_date:
            self.notice_date = fields.Date.context_today(self)
        return self.env.ref('bxi_training_policy.action_report_training_demand_notice').report_action(self)

    def action_open_payment_wizard(self):
        self.ensure_one()
        self._check_hr_or_finance()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Record Repayment'),
            'res_model': 'bxi.training.recovery.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_recovery_id': self.id},
        }

    def action_open_waive_wizard(self):
        self.ensure_one()
        if not self.env.user.has_group(ADMIN_GROUP):
            raise AccessError(self.env._("Only the Training administrators can waive a recovery."))
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Waive Recovery'),
            'res_model': 'bxi.training.recovery.waive.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_recovery_id': self.id},
        }

    def _action_register_payment(self, amount, date, reference=False, journal=False):
        self.ensure_one()
        if self.state not in OPEN_STATES:
            raise UserError(self.env._("This recovery is closed."))
        if self.currency_id.compare_amounts(amount, 0) <= 0 or self.currency_id.compare_amounts(amount, self.balance) > 0:
            raise UserError(self.env._("The amount must be positive and not exceed the balance of %(balance)s.",
                                       balance=self.currency_id.format(self.balance)))
        move = False
        credit_account = self._get_credit_account()
        if journal and credit_account:
            debit_account = journal.inbound_payment_method_line_ids.payment_account_id[:1] or journal.default_account_id
            label = self.env._("Training recovery %(name)s - repayment", name=self.name)
            move = self._post_entry(journal, date, label, debit_account, credit_account, amount)
        self.sudo().line_ids = [fields.Command.create({
            'date': date, 'amount': amount, 'source': 'payment', 'reference': reference,
            'move_id': move.id if move else False,
        })]
        self._check_closed()

    def _action_waive(self, reason):
        if not self.env.su and not self.env.user.has_group(ADMIN_GROUP):
            raise AccessError(self.env._("Only the Training administrators can waive a recovery."))
        today = fields.Date.context_today(self)
        for rec in self.sudo():
            if rec.state not in OPEN_STATES:
                raise UserError(self.env._("Only open recoveries can be waived."))
            company = rec.company_id
            credit = rec._get_credit_account()
            expense = company.trn_expense_account_id
            if credit and expense and credit != expense and company.trn_misc_journal_id \
                    and rec.currency_id.compare_amounts(rec.balance, 0) > 0:
                label = self.env._("Training recovery %(name)s waived", name=rec.name)
                rec._post_entry(company.trn_misc_journal_id, today, label, expense, credit, rec.balance)
            rec.write({'state': 'waived', 'waive_reason': reason})
            rec.agreement_id._on_recovery_closed('waived')
            rec._notify_employee(self.env._("%(name)s has been waived.", name=rec.name))

    # ── Payroll ──────────────────────────────────────────────────────────
    def _register_payroll_recovery(self, payslip, recovered):
        """Allocate the amount deducted by a confirmed payslip, oldest recovery first."""
        remaining = recovered
        for rec in self.sorted(lambda r: (r.payroll_month or fields.Date.today(), r.id)):
            currency = rec.currency_id
            take = currency.round(min(remaining, rec.balance))
            remaining = currency.round(remaining - take)
            if currency.compare_amounts(take, 0) > 0:
                move = rec._post_payroll_move(payslip, take)
                rec.line_ids = [fields.Command.create({
                    'date': payslip.date_to, 'amount': take, 'source': 'payroll', 'payslip_id': payslip.id,
                    'reference': payslip.number or payslip.name, 'move_id': move.id if move else False,
                })]
            if currency.compare_amounts(rec.balance, 0) > 0:
                rec._on_payroll_shortfall(payslip)
        self._check_closed()

    def _post_payroll_move(self, payslip, amount):
        self.ensure_one()
        company = self.company_id
        credit = self._get_credit_account()
        if not (company.trn_recovery_account_id and company.trn_misc_journal_id and credit):
            return False
        label = self.env._("Training recovery %(name)s (%(slip)s)", name=self.name, slip=payslip.number or payslip.name)
        return self._post_entry(company.trn_misc_journal_id, payslip.date_to, label,
                                company.trn_recovery_account_id, credit, amount)

    def _on_payroll_shortfall(self, payslip):
        """What the payslip could not cover: followed up legally after the Full and Final Settlement,
        otherwise carried forward to the next payroll."""
        self.ensure_one()
        note = self.env._("%(balance)s could not be recovered from payslip %(slip)s.",
                          balance=self.currency_id.format(self.balance), slip=payslip.number or payslip.name)
        if self.reason == 'breach' or not self.employee_id.active:
            self.state = 'legal'
            self.message_post(body=note + ' ' + self.env._("Moved to legal follow-up."))
        else:
            self.payroll_month = payslip.date_to + relativedelta(months=1, day=1)
            self.message_post(body=note + ' ' + self.env._("Carried forward to the next payroll."))
        self._notify_group(self.company_id.sudo().trn_hr_user_id, HR_GROUP,
                           self.env._("Training recovery shortfall: %(employee)s", employee=self.employee_id.name), note)

    def _revert_payroll_recovery(self, payslips):
        lines = self.env['bxi.training.recovery.line'].sudo().search([('payslip_id', 'in', payslips.ids)])
        for move in lines.move_id.filtered(lambda m: m.state == 'posted'):
            move._reverse_moves([{'ref': self.env._("Reversal of %(ref)s", ref=move.ref)}], cancel=True)
        recoveries = lines.recovery_id
        lines.unlink()
        recoveries._reopen()
        for rec in recoveries.filtered(lambda r: r.state == 'legal'):
            rec.state = 'payroll'


class BxiTrainingRecoveryLine(models.Model):
    _name = 'bxi.training.recovery.line'
    _description = 'Training Cost Recovered'
    _order = 'date, id'

    recovery_id = fields.Many2one('bxi.training.recovery', string='Recovery', required=True, ondelete='cascade',
                                  index=True)
    currency_id = fields.Many2one(related='recovery_id.currency_id')
    date = fields.Date(string='Date', required=True)
    amount = fields.Monetary(string='Amount', currency_field='currency_id', required=True)
    source = fields.Selection([('payroll', 'Payroll'), ('payment', 'Repayment')], string='Source', required=True)
    payslip_id = fields.Many2one('hr.payslip', string='Payslip', ondelete='set null', index='btree_not_null')
    reference = fields.Char(string='Reference')
    move_id = fields.Many2one('account.move', string='Journal Entry')
