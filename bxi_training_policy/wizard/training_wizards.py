from odoo import api, fields, models
from odoo.exceptions import UserError


class BxiTrainingRefuseWizard(models.TransientModel):
    _name = 'bxi.training.refuse.wizard'
    _description = 'Refuse Training / Refer Claim Back'

    request_id = fields.Many2one('bxi.training.request', string='Training', required=True)
    is_claim = fields.Boolean(compute='_compute_is_claim')
    reason = fields.Text(string='Reason', required=True)

    @api.depends('request_id')
    def _compute_is_claim(self):
        for wizard in self:
            wizard.is_claim = wizard.request_id.state in ('claim_approval', 'finance_approval')

    def action_confirm(self):
        self.ensure_one()
        self.request_id._check_can_refuse()
        self.request_id._action_refuse(self.reason)
        return {'type': 'ir.actions.act_window_close'}


class BxiTrainingCancelWizard(models.TransientModel):
    _name = 'bxi.training.cancel.wizard'
    _description = 'Cancel Training'

    request_id = fields.Many2one('bxi.training.request', string='Training', required=True)
    advance_amount = fields.Monetary(related='request_id.advance_amount')
    currency_id = fields.Many2one(related='request_id.currency_id')
    reason = fields.Text(string='Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.request_id._check_can_cancel()
        self.request_id._action_cancel(self.reason)
        return {'type': 'ir.actions.act_window_close'}


class BxiTrainingAdvanceWizard(models.TransientModel):
    _name = 'bxi.training.advance.wizard'
    _description = 'Pay Training Advance'

    request_id = fields.Many2one('bxi.training.request', string='Training', required=True)
    company_id = fields.Many2one(related='request_id.company_id')
    currency_id = fields.Many2one(related='request_id.currency_id')
    estimated_cost = fields.Monetary(related='request_id.estimated_cost')
    amount = fields.Monetary(
        string='Advance', required=True, compute='_compute_amount', store=True, readonly=False, precompute=True,
        help="Costs the employee pays during the training. Costs the company pays to the provider directly "
             "are not advanced.")
    date = fields.Date(string='Payment Date', required=True, default=fields.Date.context_today)
    reference = fields.Char(string='Payment Reference', help="Bank transfer reference (UTR) or cheque number.")
    create_entry = fields.Boolean(
        string='Post Journal Entry', compute='_compute_create_entry', store=True, readonly=False,
        help="Debit the Training Advance account and credit the bank. Leave unticked when the payment is booked "
             "elsewhere.")
    journal_id = fields.Many2one(
        'account.journal', string='Journal', check_company=True,
        compute='_compute_create_entry', store=True, readonly=False,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]")

    @api.depends('request_id')
    def _compute_amount(self):
        for wizard in self:
            lines = wizard.request_id.cost_line_ids.filtered(lambda line: line.paid_by == 'employee')
            wizard.amount = sum(lines.mapped('estimated_amount'))

    @api.depends('request_id')
    def _compute_create_entry(self):
        for wizard in self:
            company = wizard.request_id.company_id
            wizard.create_entry = bool(company.trn_advance_account_id)
            wizard.journal_id = company.trn_journal_id

    def action_confirm(self):
        self.ensure_one()
        if not self.request_id.can_pay_advance:
            raise UserError(self.env._("Finance or Employee Services pays the advance once the training is ready."))
        if self.create_entry and not self.journal_id:
            raise UserError(self.env._("Select the journal the advance is paid from."))
        self.request_id._action_pay_advance(
            self.amount, self.date, reference=self.reference, journal=self.journal_id if self.create_entry else False)
        return {'type': 'ir.actions.act_window_close'}


class BxiTrainingCompletionWizard(models.TransientModel):
    _name = 'bxi.training.completion.wizard'
    _description = 'Training Completed'

    request_id = fields.Many2one('bxi.training.request', string='Training', required=True)
    end_date = fields.Date(
        string='Completed On', required=True, compute='_compute_end_date', store=True, readonly=False, precompute=True,
        help="The service period of the agreement starts on this date.")
    attachment_ids = fields.Many2many('ir.attachment', string='Completion Certificate')

    @api.depends('request_id')
    def _compute_end_date(self):
        today = fields.Date.context_today(self)
        for wizard in self:
            wizard.end_date = min(wizard.request_id.end_date or today, today)

    def action_confirm(self):
        self.ensure_one()
        self.request_id._action_complete(self.end_date, self.attachment_ids)
        return {'type': 'ir.actions.act_window_close'}


class BxiTrainingAgreementVerifyWizard(models.TransientModel):
    _name = 'bxi.training.agreement.verify.wizard'
    _description = 'Verify Training Service Agreement'

    agreement_id = fields.Many2one('bxi.training.agreement', string='Service Agreement', required=True)
    executed_scan_ids = fields.Many2many(related='agreement_id.executed_scan_ids')
    stamp_paper_no = fields.Char(related='agreement_id.stamp_paper_no')
    stamp_paper_value = fields.Monetary(related='agreement_id.stamp_paper_value')
    currency_id = fields.Many2one(related='agreement_id.currency_id')
    witness1_name = fields.Char(related='agreement_id.witness1_name')
    witness2_name = fields.Char(related='agreement_id.witness2_name')
    notary_name = fields.Char(related='agreement_id.notary_name')
    notarised_date = fields.Date(related='agreement_id.notarised_date')
    check_stamp_paper = fields.Boolean(string='First page is on stamp paper of the required value')
    check_employee_signature = fields.Boolean(string='Signed by the employee on every page')
    check_witnesses = fields.Boolean(string='Witness signatures present')
    check_notary = fields.Boolean(string='Attested by a notary (seal and signature)')
    check_terms = fields.Boolean(string='Amount, service period and training match the issued agreement')
    send_back_reason = fields.Text(string='Reason for Sending Back')

    def action_verify(self):
        self.ensure_one()
        if not all((self.check_stamp_paper, self.check_employee_signature, self.check_witnesses,
                    self.check_notary, self.check_terms)):
            raise UserError(self.env._("Tick every check, or send the agreement back to the employee."))
        self.agreement_id._action_verify()
        return {'type': 'ir.actions.act_window_close'}

    def action_send_back(self):
        self.ensure_one()
        if not (self.send_back_reason or '').strip():
            raise UserError(self.env._("Explain what the employee must correct."))
        self.agreement_id._action_send_back(self.send_back_reason)
        return {'type': 'ir.actions.act_window_close'}


class BxiTrainingRecoveryPaymentWizard(models.TransientModel):
    _name = 'bxi.training.recovery.payment.wizard'
    _description = 'Record Training Cost Repayment'

    recovery_id = fields.Many2one('bxi.training.recovery', string='Recovery', required=True)
    company_id = fields.Many2one(related='recovery_id.company_id')
    currency_id = fields.Many2one(related='recovery_id.currency_id')
    balance = fields.Monetary(related='recovery_id.balance')
    amount = fields.Monetary(string='Amount Received', required=True, compute='_compute_amount', store=True,
                             readonly=False, precompute=True)
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    reference = fields.Char(string='Reference')
    journal_id = fields.Many2one(
        'account.journal', string='Received In', check_company=True,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
        help="Leave empty when the receipt is booked elsewhere.")

    @api.depends('recovery_id')
    def _compute_amount(self):
        for wizard in self:
            wizard.amount = wizard.recovery_id.balance

    def action_confirm(self):
        self.ensure_one()
        self.recovery_id._check_hr_or_finance()
        self.recovery_id._action_register_payment(self.amount, self.date, self.reference, self.journal_id)
        return {'type': 'ir.actions.act_window_close'}


class BxiTrainingRecoveryWaiveWizard(models.TransientModel):
    _name = 'bxi.training.recovery.waive.wizard'
    _description = 'Waive Training Cost Recovery'

    recovery_id = fields.Many2one('bxi.training.recovery', string='Recovery', required=True)
    reason = fields.Text(string='Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.recovery_id._action_waive(self.reason)
        return {'type': 'ir.actions.act_window_close'}
