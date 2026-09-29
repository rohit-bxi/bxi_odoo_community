import logging

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from .training_mixin import HR_GROUP

_logger = logging.getLogger(__name__)

# Agreements binding the employee: leaving before the end date means repaying the training cost.
BINDING_STATES = ('executed', 'in_service')
# Execution details the employee records when uploading the notarised agreement.
EXECUTION_FIELDS = {
    'stamp_paper_no', 'stamp_paper_value', 'stamp_paper_date', 'witness1_name', 'witness2_name',
    'notary_name', 'notary_reg_no', 'notarised_date', 'executed_scan_ids',
}


class BxiTrainingAgreement(models.Model):
    """Service agreement signed for one training program (Training Policy, clauses 4 and 5)."""
    _name = 'bxi.training.agreement'
    _description = 'Training Service Agreement'
    _inherit = ['bxi.training.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default=lambda self: self.env._('New'),
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('issued', 'To Execute'),
            ('submitted', 'To Verify'),
            ('executed', 'Executed'),
            ('in_service', 'In Service'),
            ('completed', 'Completed'),
            ('breached', 'Breached'),
            ('recovered', 'Recovered'),
            ('waived', 'Waived'),
            ('superseded', 'Superseded'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status', default='draft', required=True, tracking=True, copy=False, index=True,
    )
    request_id = fields.Many2one('bxi.training.request', string='Training', required=True, readonly=True,
                                 ondelete='restrict', index=True)
    employee_id = fields.Many2one(related='request_id.employee_id', store=True, index=True, string='Employee')
    employee_user_id = fields.Many2one(related='employee_id.user_id', string='Employee User')
    company_id = fields.Many2one(related='request_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    department_id = fields.Many2one(related='request_id.department_id', store=True, string='Department')
    training_name = fields.Char(related='request_id.training_name', string='Training Program')

    # ── Terms ────────────────────────────────────────────────────────────
    signed_amount = fields.Monetary(string='Amount at Signature', currency_field='currency_id', readonly=True)
    amount = fields.Monetary(
        string='Repayable Amount', currency_field='currency_id', tracking=True,
        help="Full consolidated cost of the training, repaid without pro-rata when the employee leaves "
             "before the end of the service period.",
    )
    tier_id = fields.Many2one('bxi.training.agreement.tier', string='Tier', readonly=True)
    period_months = fields.Integer(string='Service Period (Months)', required=True, tracking=True)
    start_date = fields.Date(string='Service Starts', tracking=True, help="Day the training was completed.")
    end_date = fields.Date(string='Service Ends', compute='_compute_end_date', store=True)
    days_remaining = fields.Integer(string='Days Remaining', compute='_compute_days_remaining')

    # ── Execution ────────────────────────────────────────────────────────
    execution_mode = fields.Selection(
        [('stamp_paper', 'Stamp Paper and Notary'), ('esign', 'Electronic Signature')],
        string='Execution', required=True, default='stamp_paper', tracking=True,
        help="The policy requires the first page on stamp paper, signed, witnessed and attested by a notary. "
             "Electronic signature is kept for employees outside India.",
    )
    template_attachment_id = fields.Many2one('ir.attachment', string='Agreement Template', readonly=True, copy=False)
    issued_date = fields.Date(string='Issued On', readonly=True, copy=False)
    stamp_paper_no = fields.Char(string='Stamp Paper No.', tracking=True, copy=False)
    stamp_paper_value = fields.Monetary(
        string='Stamp Paper Value', currency_field='currency_id', copy=False,
        default=lambda self: self._get_param('stamp_paper_value', 100))
    stamp_paper_date = fields.Date(string='Stamp Paper Date', copy=False)
    witness1_name = fields.Char(string='Witness 1', copy=False)
    witness2_name = fields.Char(string='Witness 2', copy=False)
    notary_name = fields.Char(string='Notary', copy=False)
    notary_reg_no = fields.Char(string='Notary Registration No.', copy=False)
    notarised_date = fields.Date(string='Notarised On', copy=False)
    executed_scan_ids = fields.Many2many(
        'ir.attachment', 'bxi_training_agreement_scan_rel', 'agreement_id', 'attachment_id',
        string='Executed Agreement (Scan)', copy=False,
    )
    submitted_date = fields.Date(string='Submitted On', readonly=True, copy=False)
    sent_back_reason = fields.Text(string='Sent Back Because', readonly=True, copy=False)
    verified_by_id = fields.Many2one('res.users', string='Verified By', readonly=True, copy=False)
    verified_date = fields.Date(string='Verified On', readonly=True, copy=False)
    sign_request_id = fields.Many2one('sign.request', string='Signature Request', readonly=True, copy=False)

    # ── Amendment and closure ────────────────────────────────────────────
    parent_agreement_id = fields.Many2one('bxi.training.agreement', string='Amends', readonly=True, copy=False)
    addendum_ids = fields.One2many('bxi.training.agreement', 'parent_agreement_id', string='Addenda')
    is_addendum = fields.Boolean(string='Addendum', compute='_compute_is_addendum', store=True)
    completed_date = fields.Date(string='Completed On', readonly=True, copy=False)
    writeoff_move_id = fields.Many2one('account.move', string='Settle-off Entry', readonly=True, copy=False)
    breach_date = fields.Date(string='Left On', readonly=True, copy=False)
    recovery_ids = fields.One2many('bxi.training.recovery', 'agreement_id', string='Recoveries')
    expiry_notified = fields.Boolean(copy=False)
    reminder_date = fields.Date(copy=False)

    _amount_positive = models.Constraint('CHECK(amount >= 0)', 'The repayable amount cannot be negative.')

    # ── Computes ─────────────────────────────────────────────────────────
    @api.depends('start_date', 'period_months')
    def _compute_end_date(self):
        for rec in self:
            if rec.start_date and rec.period_months:
                rec.end_date = rec.start_date + relativedelta(months=rec.period_months)
            else:
                rec.end_date = False

    def _compute_days_remaining(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.days_remaining = max((rec.end_date - today).days, 0) \
                if rec.end_date and rec.state in BINDING_STATES else 0

    @api.depends('parent_agreement_id')
    def _compute_is_addendum(self):
        for rec in self:
            rec.is_addendum = bool(rec.parent_agreement_id)

    # ── CRUD ─────────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', self.env._('New')) == self.env._('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.training.agreement') or self.env._('New')
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and not self.env.user.has_group(HR_GROUP):
            if not vals.keys() <= EXECUTION_FIELDS:
                raise AccessError(self.env._("Only HR can modify a service agreement."))
            if any(rec.state != 'issued' or rec.employee_user_id != self.env.user for rec in self):
                raise UserError(self.env._("The execution details are entered by the employee before submitting."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(rec.state not in ('draft', 'cancelled') for rec in self):
            raise UserError(self.env._("Only draft or cancelled service agreements can be deleted."))

    # ── Helpers ──────────────────────────────────────────────────────────
    def _hr_responsible(self):
        self.ensure_one()
        return self.company_id.sudo().trn_hr_user_id

    def _notify_hr(self, summary, note=''):
        self.ensure_one()
        self._notify_group(self._hr_responsible(), HR_GROUP, summary, note)

    def _check_hr(self):
        if not self.env.su and not self.env.user.has_group(HR_GROUP):
            raise AccessError(self.env._("Only HR can perform this action."))

    def _is_due_on(self, date):
        """Whether the employee still owes the training cost when leaving on ``date``."""
        self.ensure_one()
        if self.state not in BINDING_STATES:
            return False
        # Training not completed yet: the service period has not even started.
        return not self.end_date or not date or self.end_date > date

    def _get_template_pdf(self):
        self.ensure_one()
        report = self.env.ref('bxi_training_policy.action_report_training_service_agreement')
        pdf, report_type = self.env['ir.actions.report'].sudo()._render_qweb_pdf(report, self.ids)
        if report_type != 'pdf':
            raise UserError(self.env._("The service agreement could not be rendered as a PDF."))
        return pdf

    # ── Issue and execution ──────────────────────────────────────────────
    def action_issue(self):
        """Generate the agreement for the employee to execute on stamp paper (or sign electronically)."""
        for rec in self:
            if rec.state not in ('draft', 'issued'):
                raise UserError(self.env._("Only draft agreements can be issued."))
            if rec.execution_mode == 'esign':
                rec.sudo().write({'state': 'issued', 'issued_date': fields.Date.context_today(rec)})
                rec._try_send_for_signature()
                continue
            pdf = rec._get_template_pdf()
            attachment = self.env['ir.attachment'].sudo().create({
                'name': f"{rec.name} - Service Agreement.pdf",
                'raw': pdf,
                'mimetype': 'application/pdf',
                'res_model': rec._name,
                'res_id': rec.id,
            })
            rec.sudo().write({
                'state': 'issued',
                'template_attachment_id': attachment.id,
                'issued_date': fields.Date.context_today(rec),
                'reminder_date': fields.Date.context_today(rec),
            })
            template = self.env.ref('bxi_training_policy.mail_template_agreement_issued', raise_if_not_found=False)
            if template and rec.employee_id.sudo().work_email:
                template.sudo().send_mail(rec.id, email_values={'attachment_ids': attachment.ids})
            rec._notify_employee(self.env._(
                "Service agreement %(name)s has been issued for the training %(training)s: print the first page on "
                "stamp paper worth %(value)s and the other pages on A4, sign it, have it witnessed and attested by "
                "a notary, then upload the scan with the stamp paper, witness and notary details.",
                name=rec.name, training=rec.training_name, value=rec.currency_id.format(rec.stamp_paper_value)),
                attachment_ids=attachment.ids)

    def action_submit_execution(self):
        """The employee uploads the executed agreement for HR to verify."""
        for rec in self:
            if rec.state != 'issued':
                raise UserError(self.env._("Only issued agreements can be submitted."))
            if not self.env.su and rec.employee_user_id != self.env.user and not self.env.user.has_group(HR_GROUP):
                raise AccessError(self.env._("Only the employee or HR can submit the executed agreement."))
            missing = [
                label for field, label in (
                    ('executed_scan_ids', self.env._("scan of the executed agreement")),
                    ('stamp_paper_no', self.env._("stamp paper number")),
                    ('stamp_paper_date', self.env._("stamp paper date")),
                    ('witness1_name', self.env._("first witness")),
                    ('witness2_name', self.env._("second witness")),
                    ('notary_name', self.env._("notary")),
                    ('notarised_date', self.env._("notarisation date")),
                ) if not rec[field]
            ]
            if missing:
                raise UserError(self.env._("Please provide: %(fields)s.", fields=', '.join(missing)))
            minimum = rec._get_param('stamp_paper_value', 100)
            if rec.currency_id.compare_amounts(rec.stamp_paper_value, minimum) < 0:
                raise UserError(self.env._("The first page must be on stamp paper worth at least %(value)s.",
                                           value=rec.currency_id.format(minimum)))
            rec.sudo().write({'state': 'submitted', 'submitted_date': fields.Date.context_today(rec),
                              'sent_back_reason': False})
            rec._notify_hr(self.env._("Verify service agreement %(name)s", name=rec.name),
                           self.env._("Executed agreement uploaded by %(employee)s.", employee=rec.employee_id.name))

    def action_open_verify_wizard(self):
        self.ensure_one()
        self._check_hr()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Verify Service Agreement'),
            'res_model': 'bxi.training.agreement.verify.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_agreement_id': self.id},
        }

    def _action_verify(self):
        self._check_hr()
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(self.env._("Only submitted agreements can be verified."))
            rec.sudo().write({
                'verified_by_id': self.env.user.id,
                'verified_date': fields.Date.context_today(rec),
            })
            rec._on_executed()

    def _action_send_back(self, reason):
        self._check_hr()
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(self.env._("Only submitted agreements can be sent back."))
            rec.sudo().write({'state': 'issued', 'sent_back_reason': reason, 'reminder_date': fields.Date.context_today(rec)})
            rec._close_activities(self.env._("Sent back"))
            rec._notify_employee(self.env._("Service agreement %(name)s was sent back: %(reason)s",
                                            name=rec.name, reason=reason))

    def _on_executed(self):
        for rec in self.sudo():
            rec.state = 'executed'
            rec.activity_unlink(['mail.mail_activity_data_todo'])
            request = rec.request_id
            parent = rec.parent_agreement_id
            if parent:
                # The addendum replaces the agreement it amends, from the same start date.
                start = parent.start_date or request.actual_end_date
                if parent.state in BINDING_STATES:
                    parent.state = 'superseded'
                request.agreement_id = rec
                if start:
                    rec._start_service(start)
            elif request.actual_end_date:
                # Agreement required once the training was already completed (actual cost).
                rec._start_service(request.actual_end_date)
            request._on_agreement_executed(rec)
            rec._notify_employee(self.env._("Service agreement %(name)s has been verified by HR.", name=rec.name))

    def action_cancel(self):
        self._check_hr()
        self._action_cancel()

    def _action_cancel(self):
        for rec in self:
            if rec.state not in ('draft', 'issued', 'submitted', 'executed'):
                raise UserError(self.env._("Agreements already in service cannot be cancelled."))
            if rec.sudo().sign_request_id.state in ('sent', 'shared'):
                rec.sudo().sign_request_id.cancel()
        self.sudo().write({'state': 'cancelled'})

    # ── Electronic signature (outside India) ─────────────────────────────
    def action_send_for_signature(self):
        for rec in self:
            if rec.execution_mode != 'esign' or rec.state != 'issued':
                raise UserError(self.env._("Only issued agreements executed electronically are sent for signature."))
            employee = rec.employee_id.sudo()
            partner = employee.work_contact_id or employee.user_id.partner_id
            if not partner or not partner.email:
                raise UserError(self.env._("%(employee)s has no work email to receive the agreement.",
                                           employee=employee.name))
            sign_request = self.env['sign.request'].sudo()._trn_create_for_pdf(
                rec._get_template_pdf(),
                name=f"{rec.name}.pdf",
                partner=partner,
                reference=self.env._("Service Agreement %(name)s", name=rec.name),
                reference_doc=rec,
                subject=self.env._("Training Service Agreement to sign"),
            )
            if rec.sudo().sign_request_id.state in ('sent', 'shared'):
                rec.sudo().sign_request_id.cancel()
            rec.sudo().sign_request_id = sign_request

    def _try_send_for_signature(self):
        for rec in self:
            try:
                with self.env.cr.savepoint():
                    rec.action_send_for_signature()
            except Exception as error:  # noqa: BLE001 - HR can send it again or record a paper copy
                message = str(error)
                _logger.warning("Could not send service agreement %s for signature: %s", rec.name, message)
                rec.sudo().message_post(body=self.env._(
                    "The agreement could not be sent for signature automatically (%(error)s).", error=message))
                rec._notify_hr(self.env._("Send service agreement %(name)s", name=rec.name), message)

    def _on_esigned(self):
        for rec in self.sudo().filtered(lambda r: r.state == 'issued'):
            rec.write({'submitted_date': fields.Date.context_today(rec), 'verified_date': fields.Date.context_today(rec)})
            rec._on_executed()

    def _get_portal_sign_url(self):
        self.ensure_one()
        sign_request = self.sudo().sign_request_id
        item = sign_request.request_item_ids[:1]
        if self.state != 'issued' or not item or sign_request.state != 'sent':
            return False
        return f'/sign/document/{sign_request.id}/{item.access_token}?portal=1'

    # ── Service period ───────────────────────────────────────────────────
    def _start_service(self, start_date):
        for rec in self.sudo().filtered(lambda r: r.state == 'executed'):
            rec.write({'state': 'in_service', 'start_date': start_date})
            rec.message_post(body=self.env._("Service period from %(start)s to %(end)s.",
                                             start=rec.start_date, end=rec.end_date))

    def _create_addendum(self, amount, tier):
        self.ensure_one()
        addendum = self.sudo().create({
            'request_id': self.request_id.id,
            'parent_agreement_id': self.id,
            'signed_amount': amount,
            'amount': amount,
            'tier_id': tier.id,
            'period_months': tier.months,
            'execution_mode': self.execution_mode,
        })
        addendum.action_issue()
        return addendum

    def _action_complete(self):
        """The service period is served: the advance is settled off."""
        today = fields.Date.context_today(self)
        for rec in self.sudo():
            rec.write({'state': 'completed', 'completed_date': today})
            company = rec.company_id
            if company.trn_accounting_mode == 'bonded' and company.trn_bonded_account_id \
                    and company.trn_expense_account_id and company.trn_misc_journal_id \
                    and not rec.currency_id.is_zero(rec.amount):
                label = self.env._("Training service agreement %(name)s served - cost settled off", name=rec.name)
                rec.writeoff_move_id = rec._post_entry(
                    company.trn_misc_journal_id, today, label, company.trn_expense_account_id,
                    company.trn_bonded_account_id, rec.amount)
            template = self.env.ref('bxi_training_policy.mail_template_agreement_completed', raise_if_not_found=False)
            if template and rec.employee_id.work_email:
                template.send_mail(rec.id)
            rec._notify_employee(self.env._(
                "You have completed the service period of agreement %(name)s: the training advance of %(amount)s "
                "is settled off and need not be paid back.", name=rec.name, amount=rec.currency_id.format(rec.amount)))

    def _action_breach(self, leaving_date, resignation=False):
        """The employee leaves before the end of the service period: the full cost is due (no pro-rata)."""
        recoveries = self.env['bxi.training.recovery']
        for rec in self.sudo().filtered(lambda r: r._is_due_on(leaving_date)):
            rec.write({'state': 'breached', 'breach_date': leaving_date})
            recoveries |= rec.request_id._create_recovery(
                'breach', rec.amount, agreement=rec, resignation=resignation,
                payroll_month=leaving_date.replace(day=1))
            template = self.env.ref('bxi_training_policy.mail_template_agreement_breached', raise_if_not_found=False)
            if template and rec.employee_id.work_email:
                template.send_mail(rec.id)
        return recoveries

    def _on_recovery_closed(self, state):
        for rec in self.sudo().filtered(lambda r: r.state == 'breached'):
            rec.state = state

    def action_view_request(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'bxi.training.request',
            'view_mode': 'form',
            'res_id': self.request_id.id,
        }

    def action_print(self):
        self.ensure_one()
        return self.env.ref('bxi_training_policy.action_report_training_service_agreement').report_action(self)

    def action_regenerate(self):
        """Issue the template again, e.g. after correcting the employee's details."""
        self._check_hr()
        for rec in self:
            if rec.state != 'issued':
                raise UserError(self.env._("Only agreements waiting for execution can be regenerated."))
        self.action_issue()

    # ── Scheduled actions ────────────────────────────────────────────────
    @api.model
    def _cron_daily(self):
        today = fields.Date.context_today(self)
        Agreement = self.sudo()
        # The service period is over and the employee is still with the company.
        for rec in Agreement.search([('state', '=', 'in_service'), ('end_date', '<', today)]):
            if rec.employee_id.active:
                rec._action_complete()
        # Agreements awaiting execution: remind the employee every few days, alert HR before the training.
        interval = int(self._get_param('agreement_reminder_days', 3))
        for rec in Agreement.search([('state', '=', 'issued')]):
            if interval and rec.reminder_date and (today - rec.reminder_date).days >= interval:
                rec._notify_employee(self.env._(
                    "Reminder: service agreement %(name)s must be executed and uploaded before the training starts "
                    "on %(start)s.", name=rec.name, start=rec.request_id.start_date))
                rec.reminder_date = today
            start = rec.request_id.start_date
            if start and not rec.request_id.actual_end_date and 0 <= (start - today).days <= 3 \
                    and rec.reminder_date != today:
                rec._notify_hr(self.env._("Service agreement not executed: %(name)s", name=rec.name),
                               self.env._("The training starts on %(start)s.", start=start))
                rec.reminder_date = today
        # Agreements ending soon.
        notice = int(self._get_param('expiry_notice_days', 30))
        for rec in Agreement.search([('state', '=', 'in_service'), ('expiry_notified', '=', False),
                                     ('end_date', '<=', today + relativedelta(days=notice))]):
            rec._notify_hr(self.env._("Service agreement ending: %(name)s", name=rec.name),
                           self.env._("%(employee)s completes the service period on %(date)s.",
                                      employee=rec.employee_id.name, date=rec.end_date))
            rec.expiry_notified = True
