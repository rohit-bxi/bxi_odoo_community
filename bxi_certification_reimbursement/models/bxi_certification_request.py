from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError, ValidationError

# States in which the request is still open, i.e. not yet reimbursed or closed.
OPEN_STATES = (
    'draft', 'rm_approval', 'academy_approval', 'approved',
    'claim_approval', 'agreement_pending', 'finance_approval',
)
# Expense states that mean the employee has been (or is being) paid.
PAID_EXPENSE_STATES = ('approved', 'posted', 'in_payment', 'paid')
# Fields only changed by the workflow methods (which run as superuser).
WORKFLOW_FIELDS = {
    'state', 'manager_id', 'lob_id', 'band4_head_id', 'cost_center_id', 'rm_approved_date',
    'claim_submit_date', 'approval_line_ids', 'service_agreement_id', 'refuse_reason',
    'udemy_max_amount', 'company_id',
}
# Fields approved by the Reporting Manager; frozen after submission.
PRE_APPROVAL_FIELDS = {
    'employee_id', 'certification_id', 'certification_name', 'certifying_body',
    'estimated_cost', 'planned_exam_date', 'cost_centre_ack', 'voucher_id',
}


class BxiCertificationRequest(models.Model):
    """One certification attempt, from the Reporting Manager's pre-approval
    before the exam to the reimbursement claim after clearing it."""
    _name = 'bxi.certification.request'
    _description = 'Certification Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('rm_approval', 'Manager Approval'),
            ('academy_approval', 'Academy Approval'),
            ('approved', 'Pre-Approved'),
            ('claim_approval', 'Claim Approval'),
            ('agreement_pending', 'Agreement Signature'),
            ('finance_approval', 'Finance Approval'),
            ('reimbursed', 'Reimbursed'),
            ('refused', 'Refused'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
        copy=False,
        index=True,
    )

    # ── Employee ─────────────────────────────────────────────────────────
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        tracking=True,
        default=lambda self: self.env.user.employee_id,
    )
    employee_user_id = fields.Many2one(related='employee_id.user_id', string='Employee User')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    manager_id = fields.Many2one(
        'hr.employee',
        string='Reporting Manager',
        readonly=True,
        copy=False,
        tracking=True,
    )
    lob_id = fields.Many2one('bxi.line.of.business', string='Line of Business', readonly=True, copy=False)
    band4_head_id = fields.Many2one('hr.employee', string='Band 4 Head', readonly=True, copy=False)
    cost_center_id = fields.Many2one(
        'account.analytic.account',
        string='Cost Centre',
        readonly=True,
        copy=False,
        help="Cost centre of the Band 4 head; the reimbursement is charged here.",
    )

    # ── Pre-approval ─────────────────────────────────────────────────────
    certification_id = fields.Many2one(
        'bxi.certification',
        string='Certification',
        tracking=True,
        help="Leave empty if the certification is not in the approved list.",
    )
    is_on_approved_list = fields.Boolean(
        string='In Approved List',
        compute='_compute_is_on_approved_list',
        store=True,
    )
    certification_name = fields.Char(
        string='Certification Name (not in list)',
        help="Exact name and version as on the certifying body's site.",
    )
    certifying_body = fields.Char(string='Certifying Body (not in list)')
    is_udemy = fields.Boolean(related='certification_id.is_udemy', string='Udemy Course', store=True)
    estimated_cost = fields.Monetary(string='Estimated Cost', currency_field='currency_id')
    planned_exam_date = fields.Date(string='Planned Exam Date')
    cost_centre_ack = fields.Boolean(
        string='Cost Centre Acknowledged',
        help="I have informed my Reporting Manager that the certification cost will be "
             "debited to the respective Band 4 and charged to the Band 4's cost centre.",
    )
    pre_approval_attachment_ids = fields.Many2many(
        'ir.attachment',
        'bxi_cert_request_pre_approval_rel',
        'request_id',
        'attachment_id',
        string='Approval Emails',
        help="Written approval from the Reporting Manager (and, for Udemy courses, "
             "the capability/training academy) obtained before the exam.",
    )
    udemy_max_amount = fields.Monetary(
        string='Approved Maximum (Udemy)',
        currency_field='currency_id',
        tracking=True,
        help="Maximum reimbursable amount approved by the academy before enrolment.",
    )
    rm_approved_date = fields.Datetime(string='Manager Approved On', readonly=True, copy=False)
    voucher_id = fields.Many2one('bxi.certification.voucher', string='Company Voucher', copy=False)

    # ── Claim ────────────────────────────────────────────────────────────
    exam_clear_date = fields.Date(string='Exam Cleared On', tracking=True, copy=False)
    attempt_passed = fields.Boolean(
        string='Exam Passed',
        copy=False,
        help="Reimbursement applies only to the successful attempt leading to certification.",
    )
    certificate_attachment_ids = fields.Many2many(
        'ir.attachment',
        'bxi_cert_request_certificate_rel',
        'request_id',
        'attachment_id',
        string='Certificate',
        copy=False,
    )
    expense_ids = fields.One2many('hr.expense', 'certification_request_id', string='Claim Lines', copy=False)
    claim_total = fields.Monetary(
        string='Claim Total',
        currency_field='currency_id',
        compute='_compute_claim_total',
        store=True,
    )
    claim_submit_date = fields.Date(string='Claim Submitted On', readonly=True, copy=False)
    claim_age_days = fields.Integer(
        string='Days Since Exam',
        compute='_compute_claim_age',
        help="Days between clearing the exam and submitting the claim.",
    )
    is_late_claim = fields.Boolean(
        string='Late Claim',
        compute='_compute_claim_age',
        help="Claimed after the allowed number of days; routed to the Reporting Manager's manager.",
    )
    approval_line_ids = fields.One2many(
        'bxi.certification.approval.line',
        'request_id',
        string='Approvals',
        copy=False,
    )
    current_approver_id = fields.Many2one(
        'hr.employee',
        string='Waiting For',
        compute='_compute_current_approver',
    )
    can_approve = fields.Boolean(compute='_compute_can_approve')
    service_agreement_id = fields.Many2one('bxi.service.agreement', string='Service Agreement', copy=False)
    refuse_reason = fields.Text(string='Refusal Reason', readonly=True, copy=False)

    # ── Computes ─────────────────────────────────────────────────────────
    @api.depends('certification_id')
    def _compute_is_on_approved_list(self):
        for rec in self:
            rec.is_on_approved_list = bool(rec.certification_id)

    @api.depends('expense_ids.total_amount')
    def _compute_claim_total(self):
        for rec in self:
            rec.claim_total = sum(rec.expense_ids.mapped('total_amount'))

    @api.depends('exam_clear_date', 'claim_submit_date')
    def _compute_claim_age(self):
        limit = self._get_policy_param('claim_days_limit', 90)
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.exam_clear_date:
                rec.claim_age_days = ((rec.claim_submit_date or today) - rec.exam_clear_date).days
            else:
                rec.claim_age_days = 0
            rec.is_late_claim = rec.claim_age_days > limit

    @api.depends('approval_line_ids.state')
    def _compute_current_approver(self):
        for rec in self:
            rec.current_approver_id = rec._get_current_approval_line().approver_id

    @api.depends_context('uid')
    @api.depends('state', 'manager_id', 'approval_line_ids.state')
    def _compute_can_approve(self):
        is_manager = self.env.user.has_group('bxi_certification_reimbursement.group_certification_manager')
        for rec in self:
            if rec.state == 'rm_approval':
                rec.can_approve = is_manager or rec.manager_id.user_id == self.env.user
            elif rec.state == 'academy_approval':
                rec.can_approve = is_manager or rec._is_academy_user()
            elif rec.state == 'claim_approval':
                line = rec._get_current_approval_line()
                rec.can_approve = bool(line) and (is_manager or line.approver_id.user_id == self.env.user)
            else:
                rec.can_approve = False

    # ── Constraints ──────────────────────────────────────────────────────
    @api.constrains('employee_id', 'certification_id', 'certification_name')
    def _check_certification(self):
        for rec in self:
            if not rec.certification_id and not rec.certification_name:
                raise ValidationError(_("Select an approved certification or enter the certification name."))

    @api.constrains('exam_clear_date')
    def _check_exam_clear_date(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.exam_clear_date and rec.exam_clear_date > today:
                raise ValidationError(_("The exam clearing date cannot be in the future."))

    # ── CRUD ─────────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.certification.request') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and not self.env.user.has_group('bxi_certification_reimbursement.group_certification_manager'):
            protected = WORKFLOW_FIELDS & vals.keys()
            academy_edit = protected == {'udemy_max_amount'} and all(
                rec.state == 'academy_approval' and rec._is_academy_user() for rec in self)
            if protected and not academy_edit:
                raise AccessError(_("These fields are set by the approval workflow: %(fields)s",
                                    fields=', '.join(sorted(protected))))
            if not protected and any(rec.state not in ('draft', 'approved') for rec in self):
                raise UserError(_("The request can no longer be modified."))
            if PRE_APPROVAL_FIELDS & vals.keys() and any(rec.state != 'draft' for rec in self):
                raise UserError(_("The certification details were approved by your manager and cannot be changed."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(rec.state not in ('draft', 'cancelled') for rec in self):
            raise UserError(_("Only draft or cancelled certification requests can be deleted."))

    # ── Helpers ──────────────────────────────────────────────────────────
    @api.model
    def _get_policy_param(self, key, default):
        value = self.env['ir.config_parameter'].sudo().get_param(
            f'bxi_certification_reimbursement.{key}', default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _get_current_approval_line(self):
        self.ensure_one()
        # Approvers are read as superuser: employees cannot read other employees' private fields.
        pending = self.sudo().approval_line_ids.filtered(lambda line: line.state == 'pending')
        return pending.sorted('sequence')[:1]

    def _is_academy_user(self):
        self.ensure_one()
        user = self.env.user
        lob = self.lob_id.sudo()
        return (
            user.has_group('bxi_certification_reimbursement.group_certification_academy')
            and (not lob or user in lob.academy_user_ids or lob.academy_head_id.user_id == user)
        )

    def _check_employee_eligibility(self):
        for rec in self:
            employee = rec.employee_id.sudo()
            employee.invalidate_recordset(['has_active_resignation'])
            if not employee.is_india_payroll:
                raise UserError(_(
                    "%(employee)s is not on the India payroll; the Certification Policy does not apply.",
                    employee=employee.name,
                ))
            if employee.has_active_resignation:
                raise UserError(_(
                    "%(employee)s has submitted a resignation and is not eligible for certification "
                    "reimbursement.",
                    employee=employee.name,
                ))

    def _notify_user(self, user, summary, note=''):
        """Create a to-do activity for a user (which also emails them)."""
        self.ensure_one()
        if user:
            self.sudo().activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=user.id,
                summary=summary,
                note=note,
            )

    def _notify_employee(self, body):
        self.ensure_one()
        partner = self.employee_id.sudo().work_contact_id or self.employee_user_id.partner_id
        self.sudo().message_post(
            body=body,
            partner_ids=partner.ids,
            subtype_xmlid='mail.mt_comment',
        )

    def _close_activities(self, feedback=False):
        self.sudo().activity_ids.filtered(lambda act: act.user_id == self.env.user).action_feedback(feedback=feedback)

    # ── Pre-approval workflow ────────────────────────────────────────────
    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft requests can be submitted."))
            rec._check_employee_eligibility()
            if not rec.cost_centre_ack:
                raise UserError(_(
                    "Please confirm that you have informed your Reporting Manager that the cost "
                    "will be charged to the Band 4 head's cost centre."
                ))
            employee = rec.employee_id.sudo()
            if not employee.parent_id:
                raise UserError(_("%(employee)s has no Reporting Manager.", employee=employee.name))
            rec.sudo().write({
                'state': 'rm_approval',
                'manager_id': employee.parent_id.id,
                'lob_id': employee.lob_id.id,
            })
            rec._notify_user(
                employee.parent_id.user_id,
                _("Certification pre-approval: %(employee)s", employee=employee.name),
                rec._get_certification_label(),
            )

    def action_rm_approve(self):
        for rec in self:
            if rec.state != 'rm_approval' or not rec.can_approve:
                raise UserError(_("You are not allowed to approve this request."))
            next_state = 'academy_approval' if rec.is_udemy else 'approved'
            rec.sudo().write({'state': next_state, 'rm_approved_date': fields.Datetime.now()})
            rec._close_activities(_("Approved"))
            if next_state == 'academy_approval':
                lob = rec.lob_id.sudo()
                for user in (lob.academy_head_id.user_id | lob.academy_user_ids):
                    rec._notify_user(user, _("Udemy course approval: %(employee)s", employee=rec.sudo().employee_id.name))
            else:
                rec._notify_employee(_(
                    "Your certification request has been approved. You may take the exam at your own "
                    "expense and claim the reimbursement after clearing it."
                ))

    def action_academy_approve(self):
        for rec in self:
            if rec.state != 'academy_approval' or not rec.can_approve:
                raise UserError(_("You are not allowed to approve this request."))
            if rec.udemy_max_amount <= 0:
                raise UserError(_("Enter the maximum reimbursable amount approved for this Udemy course."))
            rec.sudo().state = 'approved'
            rec._close_activities(_("Approved"))
            rec._notify_employee(_(
                "Your Udemy course has been approved by the academy. The maximum reimbursable "
                "amount is %(amount)s.",
                amount=rec.udemy_max_amount,
            ))

    def action_cancel(self):
        for rec in self:
            if rec.state not in ('draft', 'rm_approval', 'academy_approval', 'approved'):
                raise UserError(_("Only requests that have not been claimed yet can be cancelled."))
            rec.sudo().expense_ids.filtered(lambda exp: exp.state == 'draft').unlink()
            rec.sudo().state = 'cancelled'
            rec.sudo().activity_unlink(['mail.mail_activity_data_todo'])

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ('refused', 'cancelled'):
                raise UserError(_("Only refused or cancelled requests can be reset to draft."))
            rec.approval_line_ids.sudo().unlink()
            rec.sudo().expense_ids.filtered(lambda exp: exp.state in ('refused', 'draft')).write({
                'state': 'draft', 'approval_state': False,
            })
            rec.sudo().write({'state': 'draft', 'refuse_reason': False, 'claim_submit_date': False})

    def action_open_refuse_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Refuse Certification Request'),
            'res_model': 'bxi.certification.refuse.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def _get_certification_label(self):
        self.ensure_one()
        return self.certification_id.display_name or self.certification_name or ''

    # ── Claim workflow ───────────────────────────────────────────────────
    def _check_claim_is_valid(self):
        self.ensure_one()
        self._check_employee_eligibility()
        if not self.exam_clear_date:
            raise UserError(_("Enter the date on which you cleared the certification exam."))
        if not self.attempt_passed:
            raise UserError(_("Reimbursement is only applicable for the successful attempt leading to certification."))
        if not self.certificate_attachment_ids:
            raise UserError(_("Attach the certificate or the result proof."))
        expenses = self.sudo().expense_ids
        if not expenses:
            raise UserError(_("Add the claim lines (exam fee, DD charges, courier charges)."))
        for expense in expenses:
            if not expense.product_id.is_certification_expense:
                raise UserError(_(
                    "%(line)s: only certification expense categories (exam fee, DD charges, courier "
                    "charges) are reimbursable.",
                    line=expense.name,
                ))
            if expense.employee_id != self.employee_id:
                raise UserError(_("All claim lines must belong to %(employee)s.", employee=self.employee_id.name))
            if expense.state != 'draft':
                raise UserError(_("%(line)s has already been submitted.", line=expense.name))
        if self.claim_total <= 0:
            raise UserError(_("The claim total must be greater than zero."))
        if self.is_udemy:
            if not self.pre_approval_attachment_ids:
                raise UserError(_("Attach the approval email from the capability/training academy."))
            if self.claim_total > self.udemy_max_amount:
                raise UserError(_(
                    "The claim (%(total)s) exceeds the maximum amount approved by the academy (%(max)s).",
                    total=self.claim_total, max=self.udemy_max_amount,
                ))

    def _prepare_approval_lines(self):
        """Build the approval chain required by the Certification Policy."""
        self.ensure_one()
        employee = self.employee_id.sudo()
        lines = []
        role_labels = dict(self.env['bxi.certification.approval.line']._fields['role']._description_selection(self.env))

        def add(role, approver):
            if not approver:
                return
            if not approver.user_id:
                raise UserError(_(
                    "%(approver)s (%(role)s) has no user account and cannot approve the claim.",
                    approver=approver.name, role=role_labels[role],
                ))
            if approver.id in [line['approver_id'] for line in lines]:
                return
            lines.append({'role': role, 'approver_id': approver.id, 'sequence': len(lines) + 1})

        # Claims older than the limit go to the Reporting Manager's Reporting Manager.
        if self.is_late_claim:
            skip_manager = employee._get_skip_manager()
            if not skip_manager:
                raise UserError(_("%(employee)s has no Reporting Manager.", employee=employee.name))
            add('skip_manager', skip_manager)
        # Approvals run from the junior to the senior band head.
        if self.claim_total > self._get_policy_param('band4_limit', 5000):
            add('band2', employee._get_band_head(2))
        if not self.is_on_approved_list:
            add('band3', employee._get_band_head(3))
        # Band 4 head approval is always needed (it also covers claims above USD 200).
        add('band4', self.band4_head_id)
        # Certification not in the approved list: LoB Academy head as well.
        if not self.is_on_approved_list:
            academy_head = self.lob_id.sudo().academy_head_id
            if not academy_head:
                raise UserError(_(
                    "No LoB Academy head is configured for %(employee)s's Line of Business.",
                    employee=employee.name,
                ))
            add('academy', academy_head)
        return lines

    def action_submit_claim(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_("A claim can only be raised on a pre-approved certification request."))
            rec._check_claim_is_valid()
            employee = rec.employee_id.sudo()
            band4_head = employee._get_band_head(4)
            cost_center = band4_head.cost_center_id
            if not cost_center:
                raise UserError(_(
                    "No cost centre is set on the Band 4 head %(head)s. Please ask HR to configure it.",
                    head=band4_head.name,
                ))
            rec.sudo().write({
                'claim_submit_date': fields.Date.context_today(rec),
                'band4_head_id': band4_head.id,
                'cost_center_id': cost_center.id,
                'lob_id': employee.lob_id.id,
            })
            rec.approval_line_ids.sudo().unlink()
            rec.sudo().write({
                'approval_line_ids': [(0, 0, vals) for vals in rec._prepare_approval_lines()],
                'state': 'claim_approval',
            })
            rec.sudo().expense_ids.write({
                'state': 'cert_approval',
                'analytic_distribution': {str(cost_center.id): 100},
            })
            rec._notify_current_approver()

    def _notify_current_approver(self):
        self.ensure_one()
        line = self._get_current_approval_line()
        if line:
            self._notify_user(
                line.approver_id.user_id,
                _("Certification claim approval: %(employee)s", employee=self.sudo().employee_id.name),
                _("%(cert)s - %(amount)s %(currency)s",
                  cert=self._get_certification_label(), amount=self.claim_total,
                  currency=self.currency_id.name),
            )

    def action_approve_claim(self):
        for rec in self:
            if rec.state != 'claim_approval' or not rec.can_approve:
                raise UserError(_("You are not allowed to approve this claim."))
            line = rec._get_current_approval_line()
            line.sudo().write({
                'state': 'approved',
                'date': fields.Datetime.now(),
                'done_by_user_id': self.env.user.id,
            })
            rec.sudo().activity_ids.filtered(
                lambda act: act.user_id == line.approver_id.user_id
            ).action_feedback(feedback=_("Approved"))
            if rec._get_current_approval_line():
                rec._notify_current_approver()
            else:
                rec._on_claim_approved()

    def _on_claim_approved(self):
        self.ensure_one()
        months = self.env['bxi.service.agreement.tier']._get_months(self.claim_total)
        if not months:
            self._move_to_finance()
            return
        agreement = self.env['bxi.service.agreement'].sudo().create({
            'employee_id': self.employee_id.id,
            'company_id': self.company_id.id,
            'request_id': self.id,
            'amount': self.claim_total,
            'start_date': self.exam_clear_date,
            'period_months': months,
        })
        self.sudo().write({'state': 'agreement_pending', 'service_agreement_id': agreement.id})
        agreement._try_send_for_signature()
        self._notify_employee(_(
            "Your claim has been approved. As the amount is %(amount)s or above, please sign the "
            "service agreement %(agreement)s to proceed to Finance.",
            amount=self.env['bxi.service.agreement.tier']._get_min_amount(),
            agreement=agreement.name,
        ))

    def _move_to_finance(self):
        for rec in self:
            # Approvers may not have access to the employee's expenses.
            rec.sudo().expense_ids.filtered(lambda exp: exp.state == 'cert_approval').write({
                'state': 'finance_approval',
            })
            rec.sudo().state = 'finance_approval'

    def _sync_from_expenses(self):
        """Follow the Finance decision taken on the claim lines."""
        for rec in self.sudo().filtered(lambda r: r.state == 'finance_approval'):
            states = set(rec.expense_ids.mapped('state'))
            if 'refused' in states:
                rec.sudo().write({'state': 'refused', 'refuse_reason': _("Refused by Finance.")})
                rec._notify_employee(_("Your certification claim has been refused by Finance."))
            elif states and states <= set(PAID_EXPENSE_STATES):
                rec.sudo().state = 'reimbursed'
                rec._notify_employee(_("Your certification claim has been approved by Finance."))

    def _action_refuse(self, reason):
        """Refuse the request or claim. Callers check the user's rights."""
        for rec in self:
            rec.approval_line_ids.filtered(lambda line: line.state == 'pending').sudo().write({
                'state': 'refused',
                'date': fields.Datetime.now(),
                'done_by_user_id': self.env.user.id,
                'comment': reason,
            })
            rec.sudo().expense_ids.filtered(lambda exp: not exp.account_move_id).write({'state': 'refused'})
            if rec.service_agreement_id.state in ('draft', 'sent'):
                rec.service_agreement_id.sudo().action_cancel()
            rec.sudo().write({'state': 'refused', 'refuse_reason': reason})
            rec.sudo().activity_unlink(['mail.mail_activity_data_todo'])
            rec._notify_employee(_("Your certification request has been refused: %(reason)s", reason=reason))

    def _check_can_refuse(self):
        is_finance = self.env.user.has_group('hr_expense.group_hr_expense_manager')
        for rec in self:
            if rec.state in ('rm_approval', 'academy_approval', 'claim_approval') and rec.can_approve:
                continue
            if rec.state in ('agreement_pending', 'finance_approval') and (
                    is_finance or self.env.user.has_group('bxi_certification_reimbursement.group_certification_manager')):
                continue
            raise UserError(_("You are not allowed to refuse %(request)s.", request=rec.name))

    def _refuse_for_resignation(self):
        """Resigned employees are not eligible; refuse everything not yet disbursed."""
        for rec in self.filtered(lambda r: r.state in OPEN_STATES):
            posted = rec.expense_ids.filtered('account_move_id')
            rec._action_refuse(_("Ineligible: resignation submitted before disbursement."))
            if posted:
                rec.sudo().message_post(body=_(
                    "Some claim lines already have journal entries (%(moves)s). Finance must reverse "
                    "them if the payment has not been disbursed.",
                    moves=', '.join(posted.account_move_id.mapped('name')),
                ))

    # ── Smart buttons ────────────────────────────────────────────────────
    def action_view_expenses(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Claim Lines'),
            'res_model': 'hr.expense',
            'view_mode': 'list,form',
            'domain': [('certification_request_id', '=', self.id)],
            'context': {'create': False},
        }

    def action_view_agreement(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'bxi.service.agreement',
            'view_mode': 'form',
            'res_id': self.service_agreement_id.id,
        }
