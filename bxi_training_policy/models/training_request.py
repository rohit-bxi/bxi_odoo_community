import logging

from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, UserError

from .training_mixin import ADMIN_GROUP, ES_GROUP, FINANCE_GROUP, HR_GROUP

_logger = logging.getLogger(__name__)

# Trainings not started yet: cancelled when the employee resigns.
NOT_STARTED_STATES = ('draft', 'hr_review', 'form_pending', 'agreement_pending', 'ready')
# States in which the actual cost replaces the estimate.
ACTUAL_COST_STATES = ('claim_approval', 'finance_approval', 'settled')
# Expense states that mean Finance accepted the claim line.
PAID_EXPENSE_STATES = ('approved', 'posted', 'in_payment', 'paid')
# Fields only changed by the workflow methods (which run as superuser) or by HR.
WORKFLOW_FIELDS = {
    'state', 'company_id', 'manager_id', 'nominated_by_id', 'hr_notified_date', 'form_sign_request_id',
    'form_signed_date', 'form_escalated', 'agreement_id', 'advance_amount', 'advance_date',
    'advance_reference', 'advance_move_id', 'actual_end_date', 'completed_by_id', 'completed_date',
    'claim_submit_date', 'approval_line_ids', 'settlement_move_id', 'settled_date', 'refuse_reason',
    'cancel_reason', 'claim_reminder_sent', 'completion_prompted',
}
# Nomination details; frozen once HR has been notified.
NOMINATION_FIELDS = {
    'employee_id', 'training_name', 'provider_id', 'location', 'scope', 'purpose', 'project_ref',
    'start_date', 'end_date', 'short_notice_reason',
}


class BxiTrainingRequest(models.Model):
    """One specialized training program of one employee, from the Department Head's nomination
    to the settlement of its cost."""
    _name = 'bxi.training.request'
    _description = 'Specialized Training'
    _inherit = ['bxi.training.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'start_date desc, id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default=lambda self: self.env._('New'),
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('hr_review', 'HR Review'),
            ('form_pending', 'Training Agreement Form'),
            ('agreement_pending', 'Service Agreement'),
            ('ready', 'Ready'),
            ('in_training', 'In Training'),
            ('completed', 'Completed'),
            ('claim_approval', 'Claim Approval'),
            ('finance_approval', 'Finance Approval'),
            ('settled', 'Settled'),
            ('refused', 'Refused'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status', default='draft', required=True, tracking=True, copy=False, index=True,
    )

    # ── People ───────────────────────────────────────────────────────────
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True, index=True)
    employee_user_id = fields.Many2one(related='employee_id.user_id', string='Employee User')
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        compute='_compute_company_id', store=True, readonly=False, precompute=True,
    )
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    department_id = fields.Many2one(related='employee_id.department_id', store=True, string='Department')
    nominated_by_id = fields.Many2one(
        'hr.employee', string='Nominated By', tracking=True, copy=False,
        default=lambda self: self.env.user.employee_id,
        help="Department Head who selected the employee for the training.",
    )
    nominated_by_user_id = fields.Many2one(related='nominated_by_id.user_id', store=True, string='Nominated By User')
    manager_id = fields.Many2one('hr.employee', string='Reporting Manager', readonly=True, copy=False)

    # ── Training ─────────────────────────────────────────────────────────
    training_name = fields.Char(string='Training', required=True, tracking=True)
    provider_id = fields.Many2one('res.partner', string='Training Provider', tracking=True)
    location = fields.Char(string='Location', required=True, tracking=True)
    scope = fields.Selection(
        [('domestic', 'Domestic'), ('international', 'International')],
        string='Scope', required=True, default='domestic', tracking=True,
    )
    purpose = fields.Text(string='Purpose', required=True, help="Project or purpose the training supports.")
    project_ref = fields.Char(string='Project')
    start_date = fields.Date(string='Start Date', required=True, tracking=True)
    end_date = fields.Date(string='End Date', required=True, tracking=True)
    duration_days = fields.Integer(string='Duration (Days)', compute='_compute_duration_days', store=True)

    # ── Notice to HR ─────────────────────────────────────────────────────
    hr_notified_date = fields.Date(string='HR Notified On', readonly=True, copy=False)
    lead_days = fields.Integer(
        string='Notice (Days)', compute='_compute_lead_days', store=True,
        help="Days between notifying HR and the start of the training.",
    )
    is_short_notice = fields.Boolean(
        string='Short Notice', compute='_compute_lead_days', store=True,
        help="HR was informed later than the policy requires (20 days before the training).",
    )
    short_notice_reason = fields.Text(string='Short Notice Reason')

    # ── Training Agreement Form ──────────────────────────────────────────
    form_due_date = fields.Date(
        string='Form Due By', compute='_compute_form_due_date', store=True,
        help="The form is signed at least 7 days before the training, or before it starts on short notice.",
    )
    form_sign_request_id = fields.Many2one('sign.request', string='Form Signature', readonly=True, copy=False)
    form_signed_date = fields.Date(string='Form Signed On', readonly=True, copy=False, tracking=True)
    form_attachment_ids = fields.Many2many(
        'ir.attachment', 'bxi_training_request_form_rel', 'request_id', 'attachment_id',
        string='Signed Form (Paper)', copy=False,
        help="Scanned Training Agreement Form when it was signed on paper instead of electronically.",
    )
    form_escalated = fields.Boolean(copy=False)

    # ── Cost ─────────────────────────────────────────────────────────────
    cost_line_ids = fields.One2many('bxi.training.cost.line', 'request_id', string='Cost', copy=True)
    estimated_cost = fields.Monetary(
        string='Estimated Cost', currency_field='currency_id', compute='_compute_costs', store=True)
    company_paid_cost = fields.Monetary(
        string='Paid by the Company', currency_field='currency_id', compute='_compute_costs', store=True)
    claim_total = fields.Monetary(
        string='Claimed by the Employee', currency_field='currency_id', compute='_compute_costs', store=True)
    actual_cost = fields.Monetary(
        string='Actual Cost', currency_field='currency_id', compute='_compute_costs', store=True)
    consolidated_cost = fields.Monetary(
        string='Consolidated Cost', currency_field='currency_id', compute='_compute_costs', store=True,
        help="Estimated cost until the claim is submitted, then the actual cost.",
    )
    agreement_required = fields.Boolean(
        string='Service Agreement Required', compute='_compute_agreement_required',
        help="The consolidated cost reaches the service agreement threshold.",
    )

    # ── Service agreement ────────────────────────────────────────────────
    agreement_id = fields.Many2one('bxi.training.agreement', string='Service Agreement', readonly=True, copy=False)
    agreement_state = fields.Selection(related='agreement_id.state', string='Agreement Status')
    agreement_ids = fields.One2many('bxi.training.agreement', 'request_id', string='Agreements')

    # ── Advance ──────────────────────────────────────────────────────────
    advance_amount = fields.Monetary(string='Advance Paid', currency_field='currency_id', readonly=True, copy=False)
    advance_date = fields.Date(string='Advance Paid On', readonly=True, copy=False, tracking=True)
    advance_reference = fields.Char(string='Advance Reference', readonly=True, copy=False)
    advance_move_id = fields.Many2one('account.move', string='Advance Entry', readonly=True, copy=False)

    # ── Completion ───────────────────────────────────────────────────────
    actual_end_date = fields.Date(string='Completed On', readonly=True, copy=False, tracking=True)
    completion_attachment_ids = fields.Many2many(
        'ir.attachment', 'bxi_training_request_completion_rel', 'request_id', 'attachment_id',
        string='Completion Certificate', copy=False,
    )
    completed_by_id = fields.Many2one('res.users', string='Completion Confirmed By', readonly=True, copy=False)
    completed_date = fields.Date(string='Completion Confirmed On', readonly=True, copy=False)
    completion_prompted = fields.Boolean(copy=False)

    # ── Claim ────────────────────────────────────────────────────────────
    expense_ids = fields.One2many('hr.expense', 'training_request_id', string='Claim Lines', copy=False)
    claim_due_date = fields.Date(string='Claim Due By', compute='_compute_claim_due_date', store=True)
    claim_submit_date = fields.Date(string='Claim Submitted On', readonly=True, copy=False)
    is_late_claim = fields.Boolean(string='Late Claim', compute='_compute_is_late_claim')
    claim_reminder_sent = fields.Boolean(copy=False)
    approval_line_ids = fields.One2many('bxi.training.approval.line', 'request_id', string='Approvals', copy=False)
    current_approval_line_id = fields.Many2one(
        'bxi.training.approval.line', string='Current Approval', compute='_compute_current_approval')
    can_approve = fields.Boolean(compute='_compute_can_act')

    # ── Settlement ───────────────────────────────────────────────────────
    settlement_move_id = fields.Many2one('account.move', string='Advance Settlement Entry', readonly=True, copy=False)
    settled_date = fields.Date(string='Settled On', readonly=True, copy=False)
    settlement_balance = fields.Monetary(
        string='Balance to Pay (+) / Recover (-)', currency_field='currency_id', compute='_compute_settlement_balance',
        help="Claimed by the employee minus the advance paid.",
    )
    recovery_ids = fields.One2many('bxi.training.recovery', 'request_id', string='Recoveries')
    refuse_reason = fields.Text(string='Refusal / Referral Reason', readonly=True, copy=False)
    cancel_reason = fields.Text(string='Cancellation Reason', readonly=True, copy=False)

    # ── Access helpers ───────────────────────────────────────────────────
    can_nominate = fields.Boolean(compute='_compute_can_act')
    is_training_hr = fields.Boolean(compute='_compute_can_act')
    can_pay_advance = fields.Boolean(compute='_compute_can_act')
    is_own = fields.Boolean(compute='_compute_can_act')

    _dates_ordered = models.Constraint(
        'CHECK(end_date >= start_date)', 'The training cannot end before it starts.',
    )

    # ── Computes ─────────────────────────────────────────────────────────
    @api.depends('employee_id')
    def _compute_company_id(self):
        for rec in self:
            rec.company_id = rec.employee_id.sudo().company_id or rec.company_id or self.env.company

    @api.depends('start_date', 'end_date')
    def _compute_duration_days(self):
        for rec in self:
            rec.duration_days = (rec.end_date - rec.start_date).days + 1 if rec.start_date and rec.end_date else 0

    @api.depends('start_date', 'hr_notified_date')
    def _compute_lead_days(self):
        minimum = self._get_param('lead_days', 20)
        today = fields.Date.context_today(self)
        for rec in self:
            notified = rec.hr_notified_date or today
            rec.lead_days = (rec.start_date - notified).days if rec.start_date else 0
            rec.is_short_notice = bool(rec.start_date) and rec.lead_days < minimum

    @api.depends('start_date', 'hr_notified_date')
    def _compute_form_due_date(self):
        form_days = int(self._get_param('form_days', 7))
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.start_date:
                rec.form_due_date = False
                continue
            due = rec.start_date - relativedelta(days=form_days)
            notified = rec.hr_notified_date or today
            # Short notice: the form is submitted before the training begins.
            rec.form_due_date = due if due >= notified else rec.start_date - relativedelta(days=1)

    @api.depends('state', 'cost_line_ids.estimated_amount', 'cost_line_ids.actual_amount',
                 'cost_line_ids.paid_by', 'expense_ids.total_amount', 'expense_ids.state')
    def _compute_costs(self):
        for rec in self:
            lines = rec.cost_line_ids
            rec.estimated_cost = sum(lines.mapped('estimated_amount'))
            rec.company_paid_cost = sum(lines.filtered(lambda line: line.paid_by == 'company').mapped('actual_amount'))
            rec.claim_total = sum(rec.expense_ids.filtered(lambda exp: exp.state != 'refused').mapped('total_amount'))
            rec.actual_cost = rec.company_paid_cost + rec.claim_total + rec._get_extra_actual_cost()
            rec.consolidated_cost = rec.actual_cost if rec.state in ACTUAL_COST_STATES else rec.estimated_cost

    def _get_extra_actual_cost(self):
        """Actual cost booked outside the training (e.g. travel requests); extended by bridge modules."""
        self.ensure_one()
        return 0.0

    @api.depends('consolidated_cost')
    def _compute_agreement_required(self):
        threshold = self._get_agreement_threshold()
        for rec in self:
            rec.agreement_required = bool(threshold) and rec.currency_id.compare_amounts(
                rec.consolidated_cost, threshold) >= 0

    @api.depends('actual_end_date')
    def _compute_claim_due_date(self):
        days = int(self._get_param('claim_days', 30))
        for rec in self:
            rec.claim_due_date = rec.actual_end_date + relativedelta(days=days) if rec.actual_end_date else False

    @api.depends('claim_due_date', 'claim_submit_date')
    def _compute_is_late_claim(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_late_claim = bool(rec.claim_due_date) and (rec.claim_submit_date or today) > rec.claim_due_date

    @api.depends('advance_amount', 'claim_total')
    def _compute_settlement_balance(self):
        for rec in self:
            rec.settlement_balance = rec.currency_id.round(rec.claim_total - rec.advance_amount)

    @api.depends('approval_line_ids.state')
    def _compute_current_approval(self):
        for rec in self:
            rec.current_approval_line_id = rec._get_current_approval_line()

    @api.depends_context('uid')
    @api.depends('state', 'employee_id', 'approval_line_ids.state')
    def _compute_can_act(self):
        user = self.env.user
        is_hr = user.has_group(HR_GROUP)
        is_admin = user.has_group(ADMIN_GROUP)
        can_pay = user.has_group(FINANCE_GROUP) or user.has_group(ES_GROUP)
        for rec in self:
            rec.is_training_hr = is_hr
            rec.is_own = rec.sudo().employee_id.user_id == user
            rec.can_nominate = rec._user_can_nominate(user)
            rec.can_pay_advance = can_pay and rec.state in ('ready', 'in_training') and not rec.advance_date
            line = rec._get_current_approval_line() if rec.state == 'claim_approval' else False
            rec.can_approve = bool(line) and (is_admin or line._is_approver(user))

    # ── CRUD ─────────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', self.env._('New')) == self.env._('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.training.request') or self.env._('New')
        records = super().create(vals_list)
        if not self.env.su:
            for rec in records:
                if not rec._user_can_nominate(self.env.user):
                    raise AccessError(self.env._(
                        "Only the Department Head of %(employee)s or HR can nominate them for a training.",
                        employee=rec.sudo().employee_id.name))
        return records

    def write(self, vals):
        if not self.env.su and not self.env.user.has_group(HR_GROUP):
            protected = WORKFLOW_FIELDS & vals.keys()
            if protected:
                raise AccessError(self.env._("These fields are set by the workflow: %(fields)s",
                                             fields=', '.join(sorted(protected))))
            if NOMINATION_FIELDS & vals.keys():
                if any(rec.state != 'draft' for rec in self):
                    raise UserError(self.env._("The nomination has been sent to HR and can no longer be modified."))
                if any(not rec._user_can_nominate(self.env.user) for rec in self):
                    raise AccessError(self.env._("Only the Department Head or HR can modify the nomination."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(rec.state not in ('draft', 'cancelled') for rec in self):
            raise UserError(self.env._("Only draft or cancelled trainings can be deleted."))
        if not self.env.su and any(not rec._user_can_nominate(self.env.user) for rec in self):
            raise AccessError(self.env._("Only the Department Head or HR can delete a nomination."))

    # ── Helpers ──────────────────────────────────────────────────────────
    def _user_can_nominate(self, user):
        """HR, or the Department Head of the employee (the Reporting Manager when the
        department has no manager)."""
        self.ensure_one()
        if user.has_group(HR_GROUP):
            return True
        employee = self.sudo().employee_id
        department_head = employee.department_id.manager_id
        head = department_head or employee.parent_id
        return bool(head) and head.user_id == user and employee.user_id != user

    def _get_current_approval_line(self):
        self.ensure_one()
        pending = self.sudo().approval_line_ids.filtered(lambda line: line.state == 'pending')
        return pending.sorted('sequence')[:1]

    def _check_employee_eligibility(self):
        for rec in self:
            employee = rec.employee_id.sudo()
            if not employee.active:
                raise UserError(self.env._("%(employee)s is archived.", employee=employee.name))
            if employee._trn_has_active_resignation():
                raise UserError(self.env._(
                    "%(employee)s has submitted a resignation and cannot be nominated for a training.",
                    employee=employee.name))

    def _hr_responsible(self):
        self.ensure_one()
        return self.company_id.sudo().trn_hr_user_id

    def _notify_hr(self, summary, note=''):
        self.ensure_one()
        self._notify_group(self._hr_responsible(), HR_GROUP, summary, note)

    def _notify_finance(self, summary, note=''):
        self.ensure_one()
        self._notify_group(self.company_id.sudo().trn_finance_user_id, FINANCE_GROUP, summary, note)

    def _check_hr(self):
        if not self.env.su and not self.env.user.has_group(HR_GROUP):
            raise AccessError(self.env._("Only HR can perform this action."))

    # ── Nomination ───────────────────────────────────────────────────────
    def action_submit(self):
        """Department Head informs HR of the employee selected for the training."""
        lead_minimum = int(self._get_param('lead_days', 20))
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.state != 'draft':
                raise UserError(self.env._("Only draft trainings can be sent to HR."))
            if not rec._user_can_nominate(self.env.user) and not self.env.su:
                raise AccessError(self.env._("Only the Department Head or HR can send the nomination to HR."))
            rec._check_employee_eligibility()
            if rec.start_date < today:
                raise UserError(self.env._("The training has already started."))
            if not rec.cost_line_ids or rec.currency_id.compare_amounts(rec.estimated_cost, 0) <= 0:
                raise UserError(self.env._("Enter the estimated cost of the training (fee, boarding and lodging, "
                                           "material, travel)."))
            if (rec.start_date - today).days < lead_minimum and not (rec.short_notice_reason or '').strip():
                raise UserError(self.env._(
                    "HR must be informed at least %(days)s days before the training. Explain why the notice is "
                    "shorter.", days=lead_minimum))
            employee = rec.employee_id.sudo()
            rec.sudo().write({
                'state': 'hr_review',
                'hr_notified_date': today,
                'nominated_by_id': rec.nominated_by_id.id or self.env.user.employee_id.id,
                'manager_id': employee.parent_id.id,
            })
            rec._notify_hr(
                self.env._("Training nomination: %(employee)s", employee=employee.name),
                self.env._("%(training)s from %(start)s%(short)s", training=rec.training_name, start=rec.start_date,
                           short=self.env._(" (short notice)") if rec.is_short_notice else ''))

    def action_hr_confirm(self):
        """HR confirms the nomination; the employee is asked to sign the Training Agreement Form."""
        self._check_hr()
        for rec in self:
            if rec.state != 'hr_review':
                raise UserError(self.env._("Only trainings in HR review can be confirmed."))
            rec._check_employee_eligibility()
            rec.sudo().state = 'form_pending'
            rec._close_activities(self.env._("Confirmed"))
            rec.sudo().activity_unlink(['mail.mail_activity_data_todo'])
            rec.employee_id.sudo()._trn_get_policy_status(create=True)
            rec._try_send_form()
            rec._notify_employee(self.env._(
                "You have been nominated for the training %(training)s (%(start)s to %(end)s). Please sign the "
                "Training Agreement Form by %(due)s.",
                training=rec.training_name, start=rec.start_date, end=rec.end_date, due=rec.form_due_date))

    def action_open_refuse_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Refuse'),
            'res_model': 'bxi.training.refuse.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def _check_can_refuse(self):
        for rec in self:
            if rec.state == 'claim_approval' and rec.can_approve:
                continue
            if rec.state == 'finance_approval' and (
                    self.env.user.has_group(FINANCE_GROUP) or self.env.user.has_group(ES_GROUP)):
                continue
            if rec.state in ('hr_review', 'form_pending', 'agreement_pending') and self.env.user.has_group(HR_GROUP):
                continue
            raise UserError(self.env._("You are not allowed to refuse %(name)s.", name=rec.name))

    def _action_refuse(self, reason):
        """Refuse the nomination, or refer a claim back to the employee."""
        for rec in self:
            if rec.state in ('claim_approval', 'finance_approval'):
                rec._refer_claim_back(reason)
                continue
            rec._cancel_documents()
            rec.sudo().write({'state': 'refused', 'refuse_reason': reason})
            rec.sudo().activity_unlink(['mail.mail_activity_data_todo'])
            rec._notify_employee(self.env._("The training %(training)s has been refused: %(reason)s",
                                            training=rec.training_name, reason=reason))

    def _refer_claim_back(self, reason):
        """The claim goes back to the employee to be corrected (e.g. filed under the wrong category)."""
        self.ensure_one()
        rec = self.sudo()
        rec.approval_line_ids.filtered(lambda line: line.state == 'pending').write({
            'state': 'refused', 'date': fields.Datetime.now(), 'done_by_user_id': self.env.user.id,
            'comment': reason,
        })
        rec.expense_ids.filtered(lambda exp: not exp.account_move_id).write({'state': 'draft', 'approval_state': False})
        rec.write({'state': 'completed', 'refuse_reason': reason, 'claim_submit_date': False})
        rec.activity_unlink(['mail.mail_activity_data_todo'])
        self._notify_employee(self.env._("Your training claim has been referred back: %(reason)s", reason=reason))

    def _cancel_documents(self):
        for rec in self.sudo():
            if rec.form_sign_request_id.state in ('sent', 'shared'):
                rec.form_sign_request_id.cancel()
            rec.agreement_ids.filtered(lambda a: a.state in ('draft', 'issued', 'submitted'))._action_cancel()

    def action_open_cancel_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Cancel Training'),
            'res_model': 'bxi.training.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def _check_can_cancel(self):
        for rec in self:
            if rec.state == 'draft' and rec._user_can_nominate(self.env.user):
                continue
            if rec.state in NOT_STARTED_STATES + ('in_training',) and self.env.user.has_group(HR_GROUP):
                continue
            raise UserError(self.env._("You are not allowed to cancel %(name)s.", name=rec.name))

    def _action_cancel(self, reason):
        """Cancel a training that has not been completed. An advance already paid is recovered."""
        for rec in self:
            if rec.state not in NOT_STARTED_STATES + ('in_training',):
                raise UserError(self.env._("Only trainings not completed yet can be cancelled."))
            rec._cancel_documents()
            rec.agreement_ids.filtered(lambda a: a.state == 'executed').sudo()._action_cancel()
            rec.sudo().write({'state': 'cancelled', 'cancel_reason': reason})
            rec.sudo().activity_unlink(['mail.mail_activity_data_todo'])
            if rec.advance_date and rec.currency_id.compare_amounts(rec.advance_amount, 0) > 0:
                rec._create_recovery('cancelled', rec.advance_amount)
            rec._notify_employee(self.env._("The training %(training)s has been cancelled: %(reason)s",
                                            training=rec.training_name, reason=reason))

    def _cancel_for_resignation(self, resignation):
        """Employees serving notice are not sent for training."""
        for rec in self.filtered(lambda r: r.state in NOT_STARTED_STATES):
            rec._action_cancel(self.env._("Resignation %(name)s submitted before the training started.",
                                          name=resignation.name))

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ('refused', 'cancelled'):
                raise UserError(self.env._("Only refused or cancelled trainings can be reset to draft."))
            if rec.advance_date:
                raise UserError(self.env._("An advance was paid for this training; create a new training instead."))
            if not rec._user_can_nominate(self.env.user):
                raise AccessError(self.env._("Only the Department Head or HR can reset the nomination."))
            rec.sudo().write({
                'state': 'draft', 'refuse_reason': False, 'cancel_reason': False, 'hr_notified_date': False,
                'form_sign_request_id': False, 'form_signed_date': False, 'form_escalated': False,
                'agreement_id': False,
            })

    # ── Training Agreement Form ──────────────────────────────────────────
    def _get_signer_partner(self):
        self.ensure_one()
        employee = self.employee_id.sudo()
        partner = employee.work_contact_id or employee.user_id.partner_id
        if not partner or not partner.email:
            raise UserError(self.env._("%(employee)s has no work email to receive the form.", employee=employee.name))
        return partner

    def action_send_form(self):
        for rec in self:
            if rec.state != 'form_pending':
                raise UserError(self.env._("The Training Agreement Form is sent once HR has confirmed the nomination."))
            partner = rec._get_signer_partner()
            report = self.env.ref('bxi_training_policy.action_report_training_agreement_form')
            pdf, report_type = self.env['ir.actions.report'].sudo()._render_qweb_pdf(report, rec.ids)
            if report_type != 'pdf':
                raise UserError(self.env._("The Training Agreement Form could not be rendered as a PDF."))
            sign_request = self.env['sign.request'].sudo()._trn_create_for_pdf(
                pdf,
                name=f"{rec.name} - Training Agreement Form.pdf",
                partner=partner,
                reference=self.env._("Training Agreement Form %(name)s", name=rec.name),
                reference_doc=rec,
                subject=self.env._("Training Agreement Form to sign"),
            )
            old_request = rec.sudo().form_sign_request_id
            if old_request.state in ('sent', 'shared'):
                old_request.cancel()
            rec.sudo().form_sign_request_id = sign_request

    def _try_send_form(self):
        """Send the form for signature without blocking the workflow if it fails."""
        for rec in self:
            try:
                with self.env.cr.savepoint():
                    rec.action_send_form()
            except Exception as error:  # noqa: BLE001 - HR can send it again or record a paper copy
                message = str(error)
                _logger.warning("Could not send the Training Agreement Form of %s: %s", rec.name, message)
                rec.sudo().message_post(body=self.env._(
                    "The Training Agreement Form could not be sent for signature automatically (%(error)s). "
                    "Please send it again or attach a signed paper copy.", error=message))
                rec._notify_hr(self.env._("Training Agreement Form not sent: %(name)s", name=rec.name), message)

    def action_mark_form_signed(self):
        """Record a Training Agreement Form signed on paper."""
        self._check_hr()
        for rec in self:
            if rec.state != 'form_pending':
                raise UserError(self.env._("The Training Agreement Form is not awaiting signature."))
            if not rec.form_attachment_ids:
                raise UserError(self.env._("Attach the signed Training Agreement Form."))
            if rec.sudo().form_sign_request_id.state in ('sent', 'shared'):
                rec.sudo().form_sign_request_id.cancel()
        self._on_form_signed()

    def _get_portal_sign_url(self):
        self.ensure_one()
        sign_request = self.sudo().form_sign_request_id
        item = sign_request.request_item_ids[:1]
        if self.state != 'form_pending' or not item or sign_request.state != 'sent':
            return False
        return f'/sign/document/{sign_request.id}/{item.access_token}?portal=1'

    def _on_form_signed(self):
        for rec in self.sudo().filtered(lambda r: r.state == 'form_pending'):
            rec.form_signed_date = fields.Date.context_today(rec)
            rec.message_post(body=self.env._("The Training Agreement Form has been signed."))
            if rec.agreement_required:
                agreement = rec._create_agreement(rec.consolidated_cost)
                rec.state = 'agreement_pending'
                agreement.action_issue()
            else:
                rec._set_ready()

    def _set_ready(self):
        for rec in self.sudo():
            rec.state = 'ready'
            rec._notify_hr(
                self.env._("Training ready to start: %(employee)s", employee=rec.employee_id.name),
                self.env._("%(training)s starts on %(start)s. Pay the advance if needed.",
                           training=rec.training_name, start=rec.start_date))

    # ── Service agreement ────────────────────────────────────────────────
    def _create_agreement(self, amount, start_date=False):
        self.ensure_one()
        tier = self.env['bxi.training.agreement.tier']._get_tier(amount, self.company_id)
        if not tier:
            raise UserError(self.env._(
                "No service agreement tier covers %(amount)s. Please configure the tiers.",
                amount=self.currency_id.format(amount)))
        agreement = self.env['bxi.training.agreement'].sudo().create({
            'request_id': self.id,
            'signed_amount': amount,
            'amount': amount,
            'tier_id': tier.id,
            'period_months': tier.months,
            'start_date': start_date,
        })
        self.sudo().agreement_id = agreement
        return agreement

    def _on_cost_changed(self):
        """The estimate changed after the form was signed: the agreement not executed yet follows it."""
        for rec in self.sudo():
            agreement = rec.agreement_id
            if rec.state == 'agreement_pending' and agreement.state == 'issued':
                rec._refresh_pending_agreement(rec.consolidated_cost)
            elif rec.state == 'agreement_pending' and agreement.state == 'submitted':
                rec._notify_hr(
                    self.env._("Training cost changed: %(name)s", name=rec.name),
                    self.env._("The executed agreement %(agreement)s was submitted for %(amount)s; send it back if "
                               "it must be executed again.", agreement=agreement.name,
                               amount=rec.currency_id.format(agreement.amount)))
            elif rec.state == 'ready' and rec.agreement_required \
                    and agreement.state not in ('executed', 'in_service'):
                new_agreement = rec._create_agreement(rec.consolidated_cost)
                rec.state = 'agreement_pending'
                new_agreement.action_issue()
                rec._notify_hr(
                    self.env._("Service agreement now required: %(employee)s", employee=rec.employee_id.name),
                    self.env._("The estimated cost %(amount)s reached the service agreement threshold.",
                               amount=rec.currency_id.format(rec.consolidated_cost)))

    def _refresh_pending_agreement(self, amount):
        """Update an agreement waiting for execution to a new cost and issue it again."""
        self.ensure_one()
        agreement = self.agreement_id
        if not self.agreement_required:
            agreement._action_cancel()
            self.agreement_id = False
            if self.state == 'agreement_pending':
                self._set_ready()
            return
        tier = self.env['bxi.training.agreement.tier']._get_tier(amount, self.company_id)
        if not tier or (agreement.currency_id.compare_amounts(agreement.amount, amount) == 0
                        and agreement.tier_id == tier):
            return
        agreement.write({'signed_amount': amount, 'amount': amount, 'tier_id': tier.id,
                         'period_months': tier.months})
        agreement.action_issue()

    def _on_agreement_executed(self, agreement):
        """Called when HR has verified the executed service agreement."""
        for rec in self.sudo():
            if rec.state == 'agreement_pending':
                rec._set_ready()

    def action_view_agreement(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'bxi.training.agreement',
            'view_mode': 'form',
            'res_id': self.agreement_id.id,
        }

    # ── Advance ──────────────────────────────────────────────────────────
    def action_open_advance_wizard(self):
        self.ensure_one()
        if not self.can_pay_advance:
            raise UserError(self.env._("Finance or Employee Services pays the advance once the training is ready."))
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Pay Training Advance'),
            'res_model': 'bxi.training.advance.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def _check_ready_gates(self):
        """Documents required before the advance is paid or the training starts."""
        self.ensure_one()
        issues = []
        if not self.form_signed_date:
            issues.append(self.env._("The Training Agreement Form is not signed."))
        if self.agreement_required and self.agreement_id.state not in ('executed', 'in_service'):
            issues.append(self.env._("The service agreement is not executed and verified by HR."))
        if self.employee_id.sudo()._trn_get_policy_status()['required']:
            issues.append(self.env._("The employee has not acknowledged the Training Policy."))
        return issues

    def _action_pay_advance(self, amount, date, reference=False, journal=False):
        self.ensure_one()
        if self.state not in ('ready', 'in_training') or self.advance_date:
            raise UserError(self.env._("The advance is paid once, when the training is ready."))
        issues = self._check_ready_gates()
        if issues:
            raise UserError("\n".join(issues))
        if self.currency_id.compare_amounts(amount, 0) <= 0:
            raise UserError(self.env._("The advance must be greater than zero."))
        if self.currency_id.compare_amounts(amount, self.estimated_cost) > 0:
            raise UserError(self.env._("The advance cannot exceed the estimated cost of %(cost)s.",
                                       cost=self.currency_id.format(self.estimated_cost)))
        rec = self.sudo()
        vals = {'advance_amount': amount, 'advance_date': date, 'advance_reference': reference}
        if journal:
            account = rec.company_id.trn_advance_account_id
            if not account:
                raise UserError(self.env._("Set the Training Advance Account in the Training settings."))
            credit = journal.outbound_payment_method_line_ids.payment_account_id[:1] or journal.default_account_id
            if not credit:
                raise UserError(self.env._("No account to credit the advance on was found on %(journal)s.",
                                           journal=journal.display_name))
            label = self.env._("Training advance %(name)s - %(employee)s", name=rec.name, employee=rec.employee_id.name)
            vals['advance_move_id'] = rec._post_entry(journal, date, label, account, credit, amount).id
        rec.write(vals)
        rec.activity_unlink(['mail.mail_activity_data_todo'])
        self._notify_employee(self.env._(
            "An advance of %(amount)s has been paid for the training %(training)s. Claim the actual cost after the "
            "training; the advance is settled against it.",
            amount=rec.currency_id.format(amount), training=rec.training_name))

    # ── Training ─────────────────────────────────────────────────────────
    def action_start(self):
        for rec in self:
            if rec.state != 'ready':
                raise UserError(self.env._("Only trainings ready to start can be started."))
            if not self.env.su:
                rec._check_hr()
            issues = rec._check_ready_gates()
            if issues:
                raise UserError("\n".join(issues))
            rec.sudo().state = 'in_training'

    def action_open_completion_wizard(self):
        self.ensure_one()
        self._check_hr()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Training Completed'),
            'res_model': 'bxi.training.completion.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def _action_complete(self, end_date, attachments=None):
        """The training is over: the service period of the agreement starts on its last day."""
        self.ensure_one()
        self._check_hr()
        if self.state != 'in_training':
            raise UserError(self.env._("Only trainings in progress can be completed."))
        if end_date < self.start_date:
            raise UserError(self.env._("The training cannot end before it started."))
        if end_date > fields.Date.context_today(self):
            raise UserError(self.env._("The completion date cannot be in the future."))
        rec = self.sudo()
        vals = {
            'state': 'completed',
            'actual_end_date': end_date,
            'completed_by_id': self.env.user.id,
            'completed_date': fields.Date.context_today(self),
        }
        if attachments:
            vals['completion_attachment_ids'] = [Command.link(att.id) for att in attachments]
        rec.write(vals)
        rec.activity_unlink(['mail.mail_activity_data_todo'])
        if rec.agreement_id.state == 'executed':
            rec.agreement_id._start_service(end_date)
        self._notify_employee(self.env._(
            "The training %(training)s is recorded as completed on %(date)s. Please claim its cost under "
            "\"Specialized Training\" by %(due)s.", training=rec.training_name, date=end_date, due=rec.claim_due_date))

    # ── Claim ────────────────────────────────────────────────────────────
    def _check_claim_is_valid(self):
        self.ensure_one()
        expenses = self.sudo().expense_ids.filtered(lambda exp: exp.state != 'refused')
        with_receipt = set(self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'hr.expense'), ('res_id', 'in', expenses.ids),
        ]).mapped('res_id'))
        if not expenses:
            raise UserError(self.env._("Add the claim lines (training fee, boarding and lodging, material, travel)."))
        for expense in expenses:
            if not expense.product_id.is_training_expense:
                raise UserError(self.env._(
                    "%(line)s: training costs are claimed under the \"Specialized Training\" categories only.",
                    line=expense.name))
            if expense.employee_id != self.employee_id:
                raise UserError(self.env._("All claim lines must belong to %(employee)s.",
                                           employee=self.employee_id.name))
            if expense.state != 'draft':
                raise UserError(self.env._("%(line)s has already been submitted.", line=expense.name))
            if expense.id not in with_receipt:
                raise UserError(self.env._("Attach the receipt of %(line)s.", line=expense.name))
            if self.currency_id.compare_amounts(expense.total_amount, 0) <= 0:
                raise UserError(self.env._("%(line)s: the amount must be greater than zero.", line=expense.name))

    def _prepare_approval_lines(self):
        """Initiator -> Reporting Manager -> HR -> Employee Services."""
        self.ensure_one()
        employee = self.employee_id.sudo()
        company = self.company_id.sudo()
        manager_user = employee.parent_id.user_id
        if not manager_user:
            raise UserError(self.env._("%(employee)s has no Reporting Manager with a user account.",
                                       employee=employee.name))
        lines = []
        seen_users = {employee.user_id.id}
        for role, user in (('rm', manager_user), ('hr', company.trn_hr_user_id), ('es', company.trn_es_user_id)):
            if user and user.id in seen_users:
                continue
            if user:
                seen_users.add(user.id)
            lines.append({'role': role, 'approver_user_id': user.id, 'sequence': len(lines) + 1})
        return lines

    def _get_claim_account(self):
        """Claimed cost is kept as bonded cost while a service agreement runs (bonded mode)."""
        self.ensure_one()
        company = self.company_id.sudo()
        if self.agreement_id and company.trn_accounting_mode == 'bonded' and company.trn_bonded_account_id:
            return company.trn_bonded_account_id
        return company.trn_expense_account_id

    def action_submit_claim(self):
        for rec in self:
            if rec.state != 'completed':
                raise UserError(self.env._("The claim is submitted once HR has recorded the training as completed."))
            if not self.env.su and not rec.is_own and not self.env.user.has_group(HR_GROUP):
                raise AccessError(self.env._("Only the employee or HR can submit the claim."))
            rec._check_claim_is_valid()
            sudo_rec = rec.sudo()
            sudo_rec.approval_line_ids.unlink()
            sudo_rec.write({
                'claim_submit_date': fields.Date.context_today(rec),
                'refuse_reason': False,
                'approval_line_ids': [Command.create(vals) for vals in rec._prepare_approval_lines()],
                'state': 'claim_approval',
            })
            expense_vals = {'state': 'training_approval'}
            account = rec._get_claim_account()
            if account:
                expense_vals['account_id'] = account.id
            sudo_rec.expense_ids.filtered(lambda exp: exp.state == 'draft').write(expense_vals)
            if rec.is_late_claim:
                rec.message_post(body=self.env._("Late claim: it was due by %(date)s.", date=rec.claim_due_date))
            rec._notify_current_approver()

    def _notify_current_approver(self):
        self.ensure_one()
        line = self._get_current_approval_line()
        if not line:
            return
        summary = self.env._("Training claim approval: %(employee)s", employee=self.sudo().employee_id.name)
        note = self.env._("%(training)s - %(amount)s", training=self.training_name,
                          amount=self.currency_id.format(self.claim_total))
        if line.approver_user_id:
            self._notify_user(line.approver_user_id, summary, note)
        else:
            self._notify_group(False, line._get_role_group(), summary, note)

    def action_approve_claim(self):
        for rec in self:
            if rec.state != 'claim_approval' or not rec.can_approve:
                raise UserError(self.env._("You are not allowed to approve this claim."))
            line = rec._get_current_approval_line()
            line.sudo().write({'state': 'approved', 'date': fields.Datetime.now(), 'done_by_user_id': self.env.user.id})
            rec.sudo().activity_ids.filtered(
                lambda act: act.activity_type_id == self.env.ref('mail.mail_activity_data_todo')
            ).action_feedback(feedback=self.env._("Approved"))
            if rec._get_current_approval_line():
                rec._notify_current_approver()
            else:
                rec._move_to_finance()

    def _move_to_finance(self):
        for rec in self:
            # Approvers may not have access to the employee's expenses.
            rec.sudo().expense_ids.filtered(lambda exp: exp.state == 'training_approval').write({
                'state': 'finance_approval',
            })
            rec.sudo().state = 'finance_approval'
            rec._notify_finance(
                self.env._("Training claim to pay: %(employee)s", employee=rec.employee_id.name),
                self.env._("%(amount)s claimed, advance paid %(advance)s.",
                           amount=rec.currency_id.format(rec.claim_total),
                           advance=rec.currency_id.format(rec.advance_amount)))

    def _sync_from_expenses(self):
        """Follow the Finance decision taken on the claim lines."""
        for rec in self.sudo().filtered(lambda r: r.state == 'finance_approval'):
            states = set(rec.expense_ids.mapped('state'))
            if 'refused' in states:
                rec._refer_claim_back(self.env._("Refused by Finance."))
            elif states and states <= set(PAID_EXPENSE_STATES):
                rec._action_settle()
        for rec in self.sudo().filtered(lambda r: r.state == 'settled'):
            rec._reconcile_settlement()

    def action_settle_without_claim(self):
        """Close a completed training whose cost was entirely paid by the company."""
        for rec in self:
            if rec.state != 'completed' or rec.expense_ids.filtered(lambda exp: exp.state != 'refused'):
                raise UserError(self.env._("Only completed trainings without a claim can be settled directly."))
            if not (self.env.user.has_group(ES_GROUP) or self.env.user.has_group(FINANCE_GROUP)):
                raise AccessError(self.env._("Only Employee Services or Finance can settle a training."))
            rec._action_settle()

    def _action_settle(self):
        """Net the advance against the claim and fix the final cost of the service agreement."""
        for rec in self.sudo():
            rec.write({'state': 'settled', 'settled_date': fields.Date.context_today(rec)})
            currency = rec.currency_id
            if rec.advance_date and currency.compare_amounts(rec.advance_amount, 0) > 0:
                netted = min(rec.advance_amount, rec.claim_total)
                rec._post_advance_settlement(netted)
                excess = currency.round(rec.advance_amount - rec.claim_total)
                if currency.compare_amounts(excess, 0) > 0:
                    rec._create_recovery('advance_excess', excess)
            rec._update_agreement_amount()
            rec.activity_unlink(['mail.mail_activity_data_todo'])
            rec._notify_employee(self.env._(
                "Your training claim has been settled. Consolidated cost: %(cost)s.",
                cost=currency.format(rec.consolidated_cost)))

    def _post_advance_settlement(self, amount):
        """Reduce what the company owes the employee for the claim by the advance already paid."""
        self.ensure_one()
        company = self.company_id
        journal = company.trn_misc_journal_id
        if not (self.advance_move_id and journal and company.trn_advance_account_id) or self.currency_id.is_zero(amount):
            return
        partner = self._get_employee_partner()
        payable = partner.with_company(company).property_account_payable_id
        if not payable:
            self.message_post(body=self.env._(
                "The advance of %(amount)s was not settled against the claim in accounting: %(employee)s has no "
                "payable account. Finance must record the settlement manually.",
                amount=self.currency_id.format(amount), employee=self.employee_id.name))
            return
        label = self.env._("Training advance %(name)s settled against the claim", name=self.name)
        self.settlement_move_id = self._post_entry(journal, fields.Date.context_today(self), label, payable,
                                                   company.trn_advance_account_id, amount, partner)
        self._reconcile_settlement()

    def _reconcile_settlement(self):
        """Match the settlement with the claim lines' payable and the advance, when possible."""
        self.ensure_one()
        move = self.settlement_move_id
        if not move:
            return
        for account in move.line_ids.account_id.filtered('reconcile'):
            lines = (move | self.expense_ids.account_move_id | self.advance_move_id).filtered(
                lambda m: m.state == 'posted').line_ids.filtered(
                lambda line: line.account_id == account and not line.reconciled
                and line.partner_id == move.line_ids[:1].partner_id)
            if lines.filtered(lambda line: line.move_id == move) and len(lines) > 1:
                try:
                    with self.env.cr.savepoint():
                        lines.reconcile()
                except UserError as error:
                    _logger.info("Could not reconcile the settlement of %s: %s", self.name, error)

    def _update_agreement_amount(self):
        """R7: the repayable amount is the actual consolidated cost; a higher tier needs an addendum."""
        self.ensure_one()
        amount = self.consolidated_cost
        agreement = self.agreement_id
        Tier = self.env['bxi.training.agreement.tier']
        if not agreement or agreement.state in ('cancelled', 'superseded'):
            if self.agreement_required:
                start = self.actual_end_date
                new = self._create_agreement(amount, start_date=start)
                new.action_issue()
                self._notify_hr(
                    self.env._("Service agreement required after settlement: %(employee)s",
                               employee=self.employee_id.name),
                    self.env._("The actual cost %(amount)s reached the service agreement threshold.",
                               amount=self.currency_id.format(amount)))
            return
        if agreement.state in ('draft', 'issued'):
            self._refresh_pending_agreement(amount)
            return
        if agreement.state not in ('submitted', 'executed', 'in_service'):
            self._notify_hr(
                self.env._("Actual training cost settled: %(name)s", name=self.name),
                self.env._("Agreement %(agreement)s is %(state)s; its amount (%(old)s) was not changed to the "
                           "actual cost %(new)s.", agreement=agreement.name, state=agreement.state,
                           old=self.currency_id.format(agreement.amount), new=self.currency_id.format(amount)))
            return
        agreement.amount = amount
        agreement.message_post(body=self.env._("Repayable amount updated to the actual cost %(amount)s.",
                                               amount=self.currency_id.format(amount)))
        tier = Tier._get_tier(amount, self.company_id)
        if tier and tier.months > agreement.period_months and agreement.state in ('executed', 'in_service'):
            addendum = agreement._create_addendum(amount, tier)
            self._notify_hr(
                self.env._("Service agreement addendum: %(employee)s", employee=self.employee_id.name),
                self.env._("The actual cost %(amount)s requires a service period of %(months)s months; addendum "
                           "%(name)s was issued.", amount=self.currency_id.format(amount), months=tier.months,
                           name=addendum.name))

    # ── Recovery ─────────────────────────────────────────────────────────
    def _create_recovery(self, reason, amount, agreement=False, resignation=False, payroll_month=False):
        self.ensure_one()
        today = fields.Date.context_today(self)
        recovery = self.env['bxi.training.recovery'].sudo().create({
            'request_id': self.id,
            'employee_id': self.employee_id.id,
            'agreement_id': agreement.id if agreement else False,
            'resignation_id': resignation.id if resignation else False,
            'reason': reason,
            'amount_due': amount,
            'payroll_month': payroll_month or today + relativedelta(months=1, day=1),
        })
        recovery._notify_created()
        return recovery

    # ── Navigation ───────────────────────────────────────────────────────
    def action_view_expenses(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Claim Lines'),
            'res_model': 'hr.expense',
            'view_mode': 'list,form',
            'domain': [('training_request_id', '=', self.id)],
            'context': {
                'default_training_request_id': self.id,
                'default_employee_id': self.employee_id.id,
                'create': self.state == 'completed',
            },
        }

    def action_view_recoveries(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('bxi_training_policy.action_bxi_training_recovery')
        action['domain'] = [('request_id', '=', self.id)]
        return action

    def action_print_form(self):
        self.ensure_one()
        return self.env.ref('bxi_training_policy.action_report_training_agreement_form').report_action(self)

    # ── Scheduled actions ────────────────────────────────────────────────
    @api.model
    def _cron_daily(self):
        today = fields.Date.context_today(self)
        records = self.sudo()
        # Training Agreement Form: reminders 7, 3 and 1 days before it is due, then escalation to HR.
        for rec in records.search([('state', '=', 'form_pending'), ('form_due_date', '!=', False)]):
            days_left = (rec.form_due_date - today).days
            if days_left in (7, 3, 1):
                rec._notify_employee(self.env._(
                    "Reminder: please sign the Training Agreement Form for %(training)s by %(due)s.",
                    training=rec.training_name, due=rec.form_due_date))
            elif days_left < 0 and not rec.form_escalated:
                rec._notify_hr(
                    self.env._("Training Agreement Form overdue: %(employee)s", employee=rec.employee_id.name),
                    self.env._("Due by %(due)s; the training starts on %(start)s.",
                               due=rec.form_due_date, start=rec.start_date))
                rec.form_escalated = True
        # Start the trainings whose documents are complete.
        for rec in records.search([('state', '=', 'ready'), ('start_date', '<=', today)]):
            issues = rec._check_ready_gates()
            if issues:
                rec._notify_hr(self.env._("Training cannot start: %(name)s", name=rec.name), "\n".join(issues))
                continue
            rec.action_start()
        # Ask HR to record the completion.
        for rec in records.search([('state', '=', 'in_training'), ('end_date', '<', today),
                                   ('completion_prompted', '=', False)]):
            rec._notify_hr(self.env._("Record the completion of %(name)s", name=rec.name),
                           self.env._("The training was planned to end on %(date)s.", date=rec.end_date))
            rec.completion_prompted = True
        # Claim deadline.
        claim_notice = int(self._get_param('claim_reminder_days', 7))
        for rec in records.search([('state', '=', 'completed'), ('claim_due_date', '!=', False),
                                   ('claim_reminder_sent', '=', False)]):
            days_left = (rec.claim_due_date - today).days
            if days_left <= claim_notice:
                rec._notify_employee(self.env._(
                    "Reminder: claim the cost of the training %(training)s by %(due)s under \"Specialized "
                    "Training\".", training=rec.training_name, due=rec.claim_due_date))
                if days_left < 0:
                    rec._notify_hr(self.env._("Training claim overdue: %(employee)s", employee=rec.employee_id.name))
                rec.claim_reminder_sent = True
