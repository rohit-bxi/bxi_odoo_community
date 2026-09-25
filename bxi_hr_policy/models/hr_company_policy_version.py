# -*- coding: utf-8 -*-
import mimetypes
from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import AccessError, UserError, ValidationError


class HrCompanyPolicyVersion(models.Model):
    _name = 'hr.company.policy.version'
    _description = 'Company Policy Version'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'policy_id, version_no desc'

    policy_id = fields.Many2one(
        'hr.company.policy',
        string='Policy',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(related='policy_id.company_id', store=True)
    version_no = fields.Integer(string='Version', required=True, copy=False)
    document = fields.Binary(string='Document', attachment=True, required=True, copy=False)
    filename = fields.Char(string='File Name')
    mimetype = fields.Char(compute='_compute_mimetype')
    valid_from = fields.Date(string='Valid From', required=True, default=fields.Date.context_today, tracking=True)
    valid_to = fields.Date(string='Valid To', tracking=True)
    description = fields.Char(string='Description', default='Revision')
    author_id = fields.Many2one('res.users', string='Author', default=lambda self: self.env.user, readonly=True)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    approved_date = fields.Datetime(string='Approved On', readonly=True, copy=False)
    published_date = fields.Datetime(string='Published On', readonly=True, copy=False)
    reject_reason = fields.Text(string='Rejection Reason', copy=False)
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('submitted', 'Waiting for CPO Approval'),
            ('approved', 'Approved'),
            ('published', 'Published'),
            ('superseded', 'Superseded'),
            ('rejected', 'Rejected'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
        copy=False,
    )
    acknowledgement_ids = fields.One2many('hr.policy.acknowledgement', 'version_id', string='Acknowledgements')
    preview_html = fields.Html(compute='_compute_preview_html', sanitize=False)

    _version_uniq = models.Constraint(
        'unique(policy_id, version_no)',
        'This version number already exists for the policy.',
    )

    @api.depends('policy_id.name', 'version_no')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = self.env._("%(policy)s - v%(version)s",
                                          policy=rec.policy_id.name or '', version=rec.version_no)

    @api.depends('filename')
    def _compute_mimetype(self):
        for rec in self:
            rec.mimetype = mimetypes.guess_type(rec.filename or '')[0] or 'application/pdf'

    @api.depends('document', 'filename')
    def _compute_preview_html(self):
        for rec in self:
            rec.preview_html = self.env['hr.company.policy']._build_preview_html(
                f'/bxi_hr_policy/preview/version/{rec.id}', rec.display_name, rec.filename, rec.mimetype,
            ) if rec.id and rec.document else False

    @api.constrains('valid_from', 'valid_to')
    def _check_dates(self):
        for rec in self:
            if rec.valid_to and rec.valid_to < rec.valid_from:
                raise ValidationError(self.env._("'Valid To' cannot be before 'Valid From'."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('version_no') and vals.get('policy_id'):
                last = self.search([('policy_id', '=', vals['policy_id'])], order='version_no desc', limit=1)
                vals['version_no'] = last.version_no + 1
        return super().create(vals_list)

    def write(self, vals):
        locked = vals.keys() & {'document', 'filename', 'version_no', 'policy_id'}
        if locked and not self.env.su and any(rec.state not in ('draft', 'rejected') for rec in self):
            raise UserError(self.env._("Only draft versions can be changed. Create a new version instead."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if any(rec.state not in ('draft', 'rejected') for rec in self):
            raise UserError(self.env._("Only draft or rejected versions can be deleted."))

    # ── Rights ───────────────────────────────────────────────────────────
    def _is_cpo(self):
        return self.env.su or self.env.user.has_group('bxi_hr_policy.group_policy_cpo')

    def _is_policy_manager(self):
        return self._is_cpo() or self.env.user.has_group('hr.group_hr_manager')

    # ── Workflow ─────────────────────────────────────────────────────────
    def action_submit(self):
        if not self._is_policy_manager():
            raise AccessError(self.env._("Only HR managers can submit policy versions."))
        for rec in self:
            if rec.state not in ('draft', 'rejected'):
                raise UserError(self.env._("Only draft versions can be submitted."))
            rec.write({'state': 'submitted', 'reject_reason': False})
            for user in self.env.ref('bxi_hr_policy.group_policy_cpo').sudo().user_ids:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=user.id,
                    summary=self.env._("Approve %(version)s", version=rec.display_name),
                )

    def action_approve(self):
        if not self._is_cpo():
            raise AccessError(self.env._("Only the CPO can approve policy versions."))
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(self.env._("Only submitted versions can be approved."))
            rec.write({'state': 'approved', 'approved_by_id': self.env.user.id,
                       'approved_date': fields.Datetime.now()})
            rec.activity_unlink(['mail.mail_activity_data_todo'])

    def action_reject(self):
        if not self._is_cpo():
            raise AccessError(self.env._("Only the CPO can reject policy versions."))
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(self.env._("Only submitted versions can be rejected."))
            if not rec.reject_reason:
                raise UserError(self.env._("Enter the reason for rejecting the version."))
            rec.state = 'rejected'
            rec.activity_unlink(['mail.mail_activity_data_todo'])

    def action_publish(self):
        if not self._is_policy_manager():
            raise AccessError(self.env._("Only HR managers or the CPO can publish policy versions."))
        for rec in self:
            if rec.state != 'approved':
                raise UserError(self.env._("Only versions approved by the CPO can be published."))
            previous = rec.policy_id.version_ids.filtered(lambda v: v.state == 'published')
            previous.sudo()._supersede()
            rec.sudo().write({'state': 'published', 'published_date': fields.Datetime.now()})
            rec.policy_id.sudo().write({
                'policy_document': rec.document,
                'policy_filename': rec.filename,
                'upload_date': fields.Date.context_today(rec),
            })
            if rec.policy_id.requires_acknowledgement:
                rec._create_acknowledgements()

    def _supersede(self):
        self.write({'state': 'superseded'})
        open_acks = self.acknowledgement_ids.filtered(lambda a: a.state in ('pending', 'overdue'))
        open_acks._cancel()

    # ── Acknowledgements ─────────────────────────────────────────────────
    def _create_acknowledgements(self, employees=None):
        """Create pending acknowledgements for employees in scope who have none yet."""
        self.ensure_one()
        policy = self.policy_id.sudo()
        if employees is None:
            employees = self.env['hr.employee'].sudo().search(policy._get_scope_employee_domain())
        already = set(self.sudo().acknowledgement_ids.employee_id.ids)
        employees = employees.filtered(lambda e: e.id not in already and e.user_id)
        if not employees:
            return self.env['hr.policy.acknowledgement']
        today = fields.Date.context_today(self)
        acks = self.env['hr.policy.acknowledgement'].sudo().create([{
            'employee_id': employee.id,
            'version_id': self.id,
            'requested_date': today,
            'due_date': today + timedelta(days=policy.ack_due_days),
            'statement': policy.ack_statement,
        } for employee in employees])
        acks._notify_request()
        return acks
