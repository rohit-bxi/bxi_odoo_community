from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .configuration import APPROVER_TYPES

PARAM_PREFIX = 'bxi_gift_entertainment.'
LEVEL_NUMBER = {'l1': 1, 'l2': 2, 'l3': 3, 'l4': 4}
# A missing approver is replaced by the next more senior authority.
ESCALATION = {'skip_manager': 'l4', 'l4': 'l3', 'l3': 'l2', 'l2': 'l1', 'l1': 'md', 'l3_or_manager': 'l2'}
GROUP_APPROVERS = {
    'md': 'group_gift_md',
    'ceo': 'group_gift_ceo',
    'cfo': 'group_gift_cfo',
    'board': 'group_gift_board',
    'ethics_committee': 'group_gift_ethics_committee',
    'lso': 'group_gift_lso',
    'due_diligence': 'group_gift_lso',
    'etc': 'group_gift_etc',
}
BASE_STATES = [
    ('draft', 'Draft'),
    ('submitted', 'Waiting Approval'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
    ('cancelled', 'Cancelled'),
]


class BxiGiftApprovalLine(models.Model):
    """One approval step of a gift policy record, with the users who can act on it."""
    _name = 'bxi.gift.approval.line'
    _description = 'Gift Policy Approval Step'
    _order = 'res_model, res_id, sequence, id'

    res_model = fields.Char(required=True, index=True)
    res_id = fields.Integer(required=True, index=True)
    record_name = fields.Char(string='Record')
    requester_user_id = fields.Many2one('res.users', string='Requested By')
    sequence = fields.Integer()
    approver_type = fields.Selection(APPROVER_TYPES, required=True)
    name = fields.Char(string='Step', required=True)
    user_ids = fields.Many2many('res.users', 'bxi_gift_approval_line_user_rel', 'line_id', 'user_id',
                                string='Approvers')
    approved_user_ids = fields.Many2many('res.users', 'bxi_gift_approval_line_vote_rel', 'line_id', 'user_id',
                                         string='Approved By')
    required_votes = fields.Integer(default=1)
    state = fields.Selection([
        ('waiting', 'Waiting'),
        ('pending', 'To Approve'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('skipped', 'Skipped'),
    ], default='waiting', required=True)
    comment = fields.Text()
    date_done = fields.Datetime(string='Decided On')

    def action_open_record(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
        }


class BxiGiftMixin(models.AbstractModel):
    """Requester, value, policy threshold and the sequential approval workflow."""
    _name = 'bxi.gift.mixin'
    _description = 'Gift Policy Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _gift_sequence = False
    _gift_zone_purpose = 'giving'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    employee_id = fields.Many2one(
        'hr.employee', required=True, index=True, tracking=True,
        default=lambda self: self.env.user.employee_id)
    employee_user_id = fields.Many2one(related='employee_id.user_id', store=True, string='Employee User')
    company_id = fields.Many2one(related='employee_id.company_id', store=True)
    department_id = fields.Many2one(related='employee_id.department_id', store=True)
    currency_id = fields.Many2one(
        'res.currency', required=True, default=lambda self: self.env.company.currency_id)
    amount = fields.Monetary(string='Value', currency_field='currency_id', tracking=True)
    zone_id = fields.Many2one('bxi.gift.zone', string='Region', compute='_compute_zone_id', store=True)
    threshold_id = fields.Many2one('bxi.gift.threshold', string='Policy Threshold', readonly=True, copy=False)
    threshold_amount = fields.Float(string='Value in Policy Currency', readonly=True, copy=False, digits=(16, 2))
    threshold_currency_id = fields.Many2one(related='threshold_id.currency_id', string='Policy Currency')
    policy_warning = fields.Text(readonly=True, copy=False)
    submitted_date = fields.Date(readonly=True, copy=False)
    approval_line_ids = fields.Many2many(
        'bxi.gift.approval.line', compute='_compute_approval_line_ids', string='Approvals')
    current_approval_line_id = fields.Many2one(
        'bxi.gift.approval.line', string='Current Step', compute='_compute_current_approval_line_id')
    can_approve = fields.Boolean(compute='_compute_current_approval_line_id', search='_search_can_approve')
    due_diligence_id = fields.Many2one('bxi.gift.due.diligence', string='Due Diligence', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New' and self._gift_sequence:
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(self._gift_sequence) or 'New'
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and not self._gift_is_officer() and \
                any(rec.state != 'draft' for rec in self) and \
                any(not key.startswith(('message_', 'activity_')) for key in vals):
            raise UserError(_("Only draft records can be modified. Ask the LSO team for a correction."))
        return super().write(vals)

    def unlink(self):
        if any(rec.state not in ('draft', 'cancelled') for rec in self):
            raise UserError(_("Only draft or cancelled records can be deleted."))
        self.env['bxi.gift.approval.line'].sudo().search([
            ('res_model', '=', self._name), ('res_id', 'in', self.ids)]).unlink()
        return super().unlink()

    @api.depends('employee_id')
    def _compute_zone_id(self):
        Zone = self.env['bxi.gift.zone']
        for rec in self:
            rec.zone_id = rec.employee_id and Zone._get_zone(rec._gift_zone_purpose, rec.employee_id)

    def _get_approval_lines(self):
        self.ensure_one()
        return self.env['bxi.gift.approval.line'].sudo().search([
            ('res_model', '=', self._name), ('res_id', '=', self.id)
        ], order='sequence,id')

    def _compute_approval_line_ids(self):
        Line = self.env['bxi.gift.approval.line'].sudo()
        for rec in self:
            rec.approval_line_ids = Line.search([
                ('res_model', '=', rec._name), ('res_id', '=', rec.id)
            ])

    @api.depends('employee_id')
    @api.depends_context('uid')
    def _compute_current_approval_line_id(self):
        Line = self.env['bxi.gift.approval.line'].sudo()
        for rec in self:
            lines = Line.search([
                ('res_model', '=', rec._name), ('res_id', '=', rec.id)
            ], order='sequence,id')
            line = lines.filtered(lambda l: l.state == 'pending')[:1]
            rec.current_approval_line_id = line
            rec.can_approve = bool(line) and self.env.user in line.user_ids                 and self.env.user not in line.approved_user_ids

    def _search_can_approve(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError(_("Unsupported search on 'To Approve'."))
        line_ids = self.env['bxi.gift.approval.line'].sudo().search([
            ('res_model', '=', self._name),
            ('state', '=', 'pending'),
            ('user_ids', 'in', self.env.uid),
        ])
        domain = [('id', 'in', line_ids.mapped('res_id'))]
        return domain if (operator == '=') == value else ['!'] + domain

    # ------------------------------------------------------------------
    # Policy hooks (overridden by each record type)
    # ------------------------------------------------------------------
    @api.model
    def _gift_param(self, key, default=False):
        return self.env['ir.config_parameter'].sudo().get_param(PARAM_PREFIX + key, default)

    def _gift_is_officer(self):
        return self.env.user.has_group('bxi_gift_entertainment.group_gift_lso')

    def _gift_category(self):
        raise NotImplementedError()

    def _gift_policy_date(self):
        return fields.Date.context_today(self)

    def _gift_threshold_value(self):
        """(amount, currency) compared with the policy matrix."""
        return self.amount, self.currency_id

    def _gift_requires_due_diligence(self):
        return False

    def _gift_check(self):
        """Return (blocking reasons, warnings) for the submission."""
        self.ensure_one()
        blocking, warnings = [], []
        if not self.threshold_id:
            blocking.append(_("No policy threshold is configured for this value. Contact the LSO team."))
        elif self.threshold_id.outcome == 'prohibited':
            blocking.append(_("Prohibited by the Gift and Entertainment Policy: %s",
                              self.threshold_id.note or _("the value exceeds the policy limit")))
        return blocking, warnings

    def _gift_steps(self):
        steps = list(self.threshold_id.step_ids.mapped('approver_type'))
        if self._gift_requires_due_diligence() and 'due_diligence' not in steps:
            steps.insert(0, 'due_diligence')
        return steps

    def _on_gift_approved(self):
        """Called once every approval step is approved."""
        self.write({'state': 'approved'})
        self._gift_notify_employee(_("%s was approved.", self.name))

    def _on_gift_rejected(self, reason):
        self.write({'state': 'rejected'})
        self._gift_notify_employee(_("%(name)s was rejected: %(reason)s", name=self.name, reason=reason))

    # ------------------------------------------------------------------
    # Approval engine
    # ------------------------------------------------------------------
    def _gift_set_threshold(self):
        for rec in self:
            amount, currency = rec._gift_threshold_value()
            row, converted = self.env['bxi.gift.threshold'].sudo()._find(
                rec._gift_category(), rec.zone_id, amount or 0.0, currency,
                rec.company_id or self.env.company, rec._gift_policy_date())
            rec.sudo().write({'threshold_id': row.id, 'threshold_amount': converted})

    def _gift_group_users(self, xmlid):
        company = self.company_id or self.env.company
        return self.env.ref('bxi_gift_entertainment.%s' % xmlid).sudo().all_user_ids.filtered(
            lambda user: user.active and not user.share and company in user.company_ids)

    def _gift_approver_users(self, approver_type):
        employee = self.employee_id.sudo()
        if approver_type in LEVEL_NUMBER:
            # Exact level: a missing head is escalated (and labelled) by _gift_resolve.
            return employee['l%s_head_id' % LEVEL_NUMBER[approver_type]].user_id
        if approver_type == 'skip_manager':
            return employee._gift_skip_level_manager().user_id
        if approver_type == 'l3_or_manager':
            return employee.l3_head_id.user_id or employee.parent_id.user_id
        return self._gift_group_users(GROUP_APPROVERS[approver_type])

    def _gift_resolve(self, approver_type):
        labels = dict(APPROVER_TYPES)
        requester = self.employee_id.sudo().user_id
        users = self._gift_approver_users(approver_type) - requester
        if not users:
            raise UserError(_(
                "No configured approver is available for '%(step)s' for %(employee)s. "
                "Configure the required L1-L4 Head / committee membership and retry.",
                step=labels[approver_type], employee=self.employee_id.name))
        votes = 1
        if approver_type == 'ethics_committee':
            votes = int(self._gift_param('committee_quorum', 3))
            if votes < 1:
                raise UserError(_("Ethics Committee quorum must be at least 1."))
            if len(users) < votes:
                raise UserError(_(
                    "The Ethics Committee has %(members)s eligible members but the configured quorum is %(quorum)s.",
                    members=len(users), quorum=votes))
        return users, labels[approver_type], votes

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft records can be submitted."))
            if not self.env.su and rec.employee_user_id != self.env.user and not rec._gift_is_officer():
                raise UserError(_("You can only submit your own records."))
            rec._gift_set_threshold()
            blocking, warnings = rec._gift_check()
            if blocking:
                raise UserError('\n'.join(blocking))
            rec.sudo().write({
                'policy_warning': '\n'.join(warnings) or False,
                'submitted_date': fields.Date.context_today(rec),
            })
            rec.sudo()._gift_start_approval()
        return True

    def _gift_start_approval(self):
        self.ensure_one()
        self._get_approval_lines().unlink()
        steps = self._gift_steps()
        Line = self.env['bxi.gift.approval.line']
        for sequence, step in enumerate(steps):
            users, label, votes = self._gift_resolve(step)
            Line.create({
                'res_model': self._name,
                'res_id': self.id,
                'record_name': self.name,
                'requester_user_id': self.employee_user_id.id,
                'sequence': sequence,
                'approver_type': step,
                'name': label,
                'user_ids': [(6, 0, users.ids)],
                'required_votes': votes,
            })
        self.write({'state': 'submitted'})
        self._gift_activate_next()

    def _gift_activate_next(self):
        self.ensure_one()
        line = self._get_approval_lines().filtered(lambda l: l.state == 'waiting').sorted('sequence')[:1]
        if not line:
            self._on_gift_approved()
            return
        line.state = 'pending'
        if line.approver_type == 'due_diligence':
            self._gift_ensure_due_diligence()
        for user in line.user_ids:
            self.activity_schedule(
                'mail.mail_activity_data_todo', user_id=user.id,
                summary=_("%(step)s: %(name)s", step=line.name, name=self.name))

    def _gift_ensure_due_diligence(self):
        if not self.due_diligence_id:
            self.due_diligence_id = self.env['bxi.gift.due.diligence'].create({
                'res_model': self._name,
                'res_id': self.id,
                'record_name': self.name,
                'partner_id': self._gift_counterparty().id,
                'scope': self._gift_due_diligence_scope(),
            })

    def _gift_counterparty(self):
        return self.env['res.partner']

    def _gift_due_diligence_scope(self):
        return 'gift'

    def _gift_close_activities(self, users, done_by=False):
        activities = self.sudo().activity_ids.filtered(lambda act: act.user_id in users)
        (activities.filtered(lambda act: act.user_id == done_by)).action_feedback()
        (activities.filtered(lambda act: act.user_id != done_by)).unlink()

    def action_approve(self):
        for rec in self:
            line = rec.current_approval_line_id
            if not line or self.env.user not in line.user_ids:
                raise UserError(_("You are not an approver of the current step of %s.", rec.name))
            if self.env.user in line.approved_user_ids:
                raise UserError(_("You already approved this step."))
            if line.approver_type == 'due_diligence':
                raise UserError(_("Approve the due diligence %s to complete this step.", rec.due_diligence_id.name))
            rec.sudo()._gift_approve_line(line, self.env.user)
        return True

    def _gift_approve_line(self, line, user, comment=False):
        line = line.sudo()
        line.approved_user_ids = [(4, user.id)]
        self._gift_close_activities(user, done_by=user)
        self.message_post(body=_("%(user)s approved: %(step)s.", user=user.name, step=line.name))
        if len(line.approved_user_ids) >= line.required_votes:
            line.write({'state': 'approved', 'date_done': fields.Datetime.now(), 'comment': comment or line.comment})
            self._gift_close_activities(line.user_ids)
            self._gift_activate_next()

    def action_reject(self):
        self.ensure_one()
        line = self.current_approval_line_id
        if not line or (self.env.user not in line.user_ids and not self._gift_is_officer()):
            raise UserError(_("You are not an approver of the current step of %s.", self.name))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Reject"),
            'res_model': 'bxi.gift.reason.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_res_model': self._name, 'default_res_id': self.id, 'default_action': 'reject'},
        }

    def _gift_reject(self, reason):
        self.ensure_one()
        line = self.current_approval_line_id.sudo()
        line.write({'state': 'rejected', 'comment': reason, 'date_done': fields.Datetime.now()})
        self._get_approval_lines().filtered(lambda l: l.state == 'waiting').write({'state': 'skipped'})
        self._gift_close_activities(line.user_ids)
        self.message_post(body=_("%(user)s rejected: %(reason)s", user=self.env.user.name, reason=reason))
        self._on_gift_rejected(reason)

    def action_cancel(self):
        for rec in self:
            if rec.state not in ('draft', 'submitted', 'approved'):
                raise UserError(_("%s cannot be cancelled in its current state.", rec.name))
            if not self.env.su and rec.employee_user_id != self.env.user and not rec._gift_is_officer():
                raise UserError(_("You can only cancel your own records."))
            rec._get_approval_lines().filtered(lambda l: l.state in ('waiting', 'pending')).sudo().write(
                {'state': 'skipped'})
            rec._gift_close_activities(rec._get_approval_lines().user_ids)
            rec.sudo().state = 'cancelled'
        return True

    def action_reset_draft(self):
        for rec in self:
            if rec.state not in ('rejected', 'cancelled'):
                raise UserError(_("Only rejected or cancelled records can be reset to draft."))
            if not self.env.su and rec.employee_user_id != self.env.user and not rec._gift_is_officer():
                raise UserError(_("You can only reset your own records."))
            rec.sudo().approval_line_ids.unlink()
            rec.sudo().write({'state': 'draft', 'threshold_id': False, 'policy_warning': False})
        return True

    def _gift_notify_employee(self, body):
        for rec in self:
            employee = rec.employee_id.sudo()
            partner = employee.work_contact_id or employee.user_id.partner_id
            rec.sudo().message_post(body=body, partner_ids=partner.ids, subtype_xmlid='mail.mt_comment')

    def _gift_notify_lso(self, subject, body):
        """E-mail the LSO mailbox (records and notices required by the policy)."""
        email = self._gift_param('lso_email', False)
        if email:
            self.env['mail.mail'].sudo().create({
                'subject': subject,
                'body_html': body,
                'email_to': email,
                'model': self._name,
                'res_id': self.id,
            })
        for user in self._gift_group_users('group_gift_lso'):
            self.activity_schedule('mail.mail_activity_data_todo', user_id=user.id, summary=subject)

    @api.model
    def _cron_gift_approval_reminder(self):
        """Remind approvers of steps pending for longer than the configured number of days."""
        days = int(self._gift_param('approval_reminder_days', 0))
        if days <= 0:
            return
        limit = fields.Date.subtract(fields.Date.context_today(self), days=days)
        for rec in self.sudo().search([('state', '=', 'submitted'), ('submitted_date', '<=', limit)]):
            line = rec.current_approval_line_id
            pending = line.user_ids - line.approved_user_ids
            if pending:
                rec.message_post(body=_("Reminder: %(step)s is waiting for approval since %(day)s.",
                                        step=line.name, day=rec.submitted_date),
                                 partner_ids=pending.partner_id.ids, subtype_xmlid='mail.mt_comment')
