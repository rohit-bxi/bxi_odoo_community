# -*- coding: utf-8 -*-
import mimetypes

from markupsafe import escape

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class HrCompanyPolicy(models.Model):
    _name = 'hr.company.policy'
    _description = 'HR Company Policy Document'
    _order = 'upload_date desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='Policy Document Name',
        required=True,
        tracking=True,
        help='The title or name of the company policy document.'
    )
    policy_document = fields.Binary(
        string='Policy Document',
        attachment=True,
        help='Document of the published version (set when a version is published).'
    )
    policy_filename = fields.Char(
        string='File Name'
    )
    file_type = fields.Char(
        string='File Extension',
        compute='_compute_file_info',
        store=True
    )
    mimetype = fields.Char(
        string='MIME Type',
        compute='_compute_file_info',
        store=True
    )
    upload_date = fields.Date(
        string='Upload Date',
        default=fields.Date.context_today,
        readonly=True
    )
    uploaded_by_id = fields.Many2one(
        'res.users',
        string='Uploaded By',
        default=lambda self: self.env.user,
        readonly=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company
    )
    description = fields.Text(
        string='Policy Summary / Notes'
    )
    active = fields.Boolean(
        default=True
    )
    preview_html = fields.Html(
        string='Document Viewer',
        compute='_compute_preview_html',
        sanitize=False
    )

    # ── Versions and acknowledgement ─────────────────────────────────────
    version_ids = fields.One2many('hr.company.policy.version', 'policy_id', string='Versions')
    version_count = fields.Integer(compute='_compute_version_stats')
    current_version_id = fields.Many2one(
        'hr.company.policy.version',
        string='Current Version',
        compute='_compute_version_stats',
    )
    requires_acknowledgement = fields.Boolean(
        string='Requires Acknowledgement',
        default=True,
        tracking=True,
        help="Employees in scope must acknowledge every published version.",
    )
    ack_statement = fields.Text(
        string='Acknowledgement Statement',
        default="I have read and understood this policy and agree to comply with it and to "
                "conduct all my activities in strict accordance with it.",
        help="Text the employee agrees to; it is stored with each acknowledgement.",
    )
    scope = fields.Selection(
        [
            ('all', 'All Employees'),
            ('companies', 'Selected Companies'),
            ('departments', 'Selected Departments'),
        ],
        string='Applies To',
        default='all',
        required=True,
        tracking=True,
        help="Leave the company empty to apply the policy to every company.",
    )
    scope_company_ids = fields.Many2many('res.company', string='Companies')
    scope_department_ids = fields.Many2many('hr.department', string='Departments')
    ack_due_days = fields.Integer(string='Days to Acknowledge', default=7)
    reminder_interval_days = fields.Integer(
        string='Reminder Every (Days)', default=2,
        help="0 disables reminders.")
    escalate_manager_after_days = fields.Integer(
        string='Escalate to Manager After (Days Overdue)', default=3,
        help="0 disables the escalation.")
    escalate_hr_after_days = fields.Integer(
        string='Escalate to HR After (Days Overdue)', default=7,
        help="0 disables the escalation.")
    block_portal_until_ack = fields.Boolean(
        string='Lock Employee Portal When Overdue',
        help="While an acknowledgement of this policy is overdue, the employee portal only "
             "shows the policies to acknowledge.",
    )
    acknowledgement_ids = fields.One2many('hr.policy.acknowledgement', 'policy_id', string='Acknowledgements')
    ack_total = fields.Integer(string='Requested', compute='_compute_ack_stats')
    ack_done = fields.Integer(string='Acknowledged', compute='_compute_ack_stats')
    ack_open = fields.Integer(string='Pending', compute='_compute_ack_stats')
    ack_rate = fields.Float(string='Acknowledged (%)', compute='_compute_ack_stats')

    @api.depends('version_ids.state')
    def _compute_version_stats(self):
        for policy in self:
            policy.version_count = len(policy.version_ids)
            policy.current_version_id = policy.version_ids.filtered(lambda v: v.state == 'published')[:1]

    @api.depends('current_version_id')
    def _compute_ack_stats(self):
        Ack = self.env['hr.policy.acknowledgement'].sudo()
        for policy in self:
            acks = Ack.search([
                ('version_id', '=', policy.current_version_id.id),
                ('state', '!=', 'cancelled'),
            ]) if policy.current_version_id else Ack
            done = acks.filtered(lambda a: a.state in ('acknowledged', 'waived'))
            policy.ack_total = len(acks)
            policy.ack_done = len(done)
            policy.ack_open = len(acks) - len(done)
            policy.ack_rate = 100.0 * len(done) / len(acks) if acks else 0.0

    @api.constrains('ack_due_days', 'reminder_interval_days', 'escalate_manager_after_days', 'escalate_hr_after_days')
    def _check_days(self):
        for policy in self:
            if min(policy.ack_due_days, policy.reminder_interval_days,
                   policy.escalate_manager_after_days, policy.escalate_hr_after_days) < 0:
                raise ValidationError(self.env._("The number of days cannot be negative."))

    def _get_scope_employee_domain(self):
        """Employees who must acknowledge this policy (they need a user to log in)."""
        self.ensure_one()
        domain = [('active', '=', True), ('user_id', '!=', False)]
        if self.company_id:
            domain.append(('company_id', '=', self.company_id.id))
        if self.scope == 'companies':
            domain.append(('company_id', 'in', self.scope_company_ids.ids))
        elif self.scope == 'departments':
            domain.append(('department_id', 'child_of', self.scope_department_ids.ids))
        return domain

    def _applies_to(self, employee):
        self.ensure_one()
        return bool(self.env['hr.employee'].sudo().with_context(active_test=False).search_count(
            self._get_scope_employee_domain() + [('id', '=', employee.id)]))

    def action_request_acknowledgement(self):
        """Ask employees in scope who have not been asked yet (e.g. older policies)."""
        for policy in self:
            if not policy.current_version_id:
                raise UserError(self.env._("%(policy)s has no published version.", policy=policy.name))
            if not policy.requires_acknowledgement:
                raise UserError(self.env._("%(policy)s does not require acknowledgement.", policy=policy.name))
            policy.current_version_id._create_acknowledgements()

    def action_view_versions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Versions'),
            'res_model': 'hr.company.policy.version',
            'view_mode': 'list,form',
            'domain': [('policy_id', '=', self.id)],
            'context': {'default_policy_id': self.id},
        }

    def action_view_acknowledgements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Acknowledgements'),
            'res_model': 'hr.policy.acknowledgement',
            'view_mode': 'list,pivot,graph,form',
            'domain': [('policy_id', '=', self.id)],
            'context': {'search_default_current_version': 1, 'create': False},
        }

    @api.model
    def _build_preview_html(self, url, title, filename, mimetype):
        """View-only document frame shared by policies, versions and acknowledgements."""
        fn = (filename or '').lower()
        mime = mimetype or ''
        title = escape(title or '')
        if fn.endswith(('.png', '.jpg', '.jpeg', '.webp', '.svg')) or 'image' in mime:
            body = (f'<div class="o_policy_image_wrapper"><img src="{url}" alt="{title}" '
                    f'class="o_policy_preview_img" draggable="false" oncontextmenu="return false;"/></div>')
            icon = 'fa-file-image-o text-primary'
        else:
            body = (f'<iframe src="{url}#toolbar=0&amp;navpanes=0&amp;scrollbar=1" class="o_policy_pdf_frame" '
                    f'title="{title}" frameborder="0" allow="fullscreen"></iframe>')
            icon = 'fa-file-pdf-o text-danger' if fn.endswith('.pdf') or 'pdf' in mime else 'fa-file-o text-secondary'
        return f"""
            <div class="o_policy_viewer_container" oncontextmenu="return false;">
                <div class="o_policy_viewer_header">
                    <span class="o_policy_badge"><i class="fa fa-lock me-1"></i> View Only Mode</span>
                    <span class="o_policy_title"><i class="fa {icon} me-1"></i> {title}</span>
                </div>
                {body}
            </div>
        """

    def action_open_viewer(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'hr.company.policy',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref('bxi_hr_policy.view_hr_company_policy_viewer_form').id, 'form')],
            'target': 'current',
            'flags': {'form': {'action_buttons': False}},
        }

    @api.depends('policy_filename')
    def _compute_file_info(self):
        for record in self:
            if record.policy_filename:
                ext = record.policy_filename.split('.')[-1].lower() if '.' in record.policy_filename else ''
                record.file_type = ext.upper()
                mime, _ = mimetypes.guess_type(record.policy_filename)
                record.mimetype = mime or 'application/octet-stream'
            else:
                record.file_type = 'FILE'
                record.mimetype = 'application/octet-stream'

    @api.depends('policy_document', 'policy_filename')
    def _compute_preview_html(self):
        for record in self:
            if not record.id or not record.policy_document:
                record.preview_html = """
                    <div class="o_policy_no_doc_alert">
                        <i class="fa fa-file-text-o fa-3x text-muted mb-2"></i>
                        <p class="text-muted">No policy document attached yet. Please upload a file.</p>
                    </div>
                """
                continue

            fn = (record.policy_filename or '').lower()
            mime = record.mimetype or ''

            # PDF Viewer
            if fn.endswith('.pdf') or 'pdf' in mime:
                preview_url = f"/bxi_hr_policy/preview/{record.id}#toolbar=0&navpanes=0&scrollbar=1"
                record.preview_html = f"""
                    <div class="o_policy_viewer_container" oncontextmenu="return false;">
                        <div class="o_policy_viewer_header">
                            <span class="o_policy_badge"><i class="fa fa-lock me-1"></i> View Only Mode</span>
                            <span class="o_policy_title"><i class="fa fa-file-pdf-o text-danger me-1"></i> {record.name}</span>
                        </div>
                        <iframe src="{preview_url}" 
                                class="o_policy_pdf_frame" 
                                title="{record.name}"
                                frameborder="0"
                                allow="fullscreen">
                        </iframe>
                    </div>
                """
            # Image Viewer
            elif fn.endswith(('.png', '.jpg', '.jpeg', '.webp', '.svg')) or 'image' in mime:
                preview_url = f"/bxi_hr_policy/preview/{record.id}"
                record.preview_html = f"""
                    <div class="o_policy_viewer_container" oncontextmenu="return false;">
                        <div class="o_policy_viewer_header">
                            <span class="o_policy_badge"><i class="fa fa-lock me-1"></i> View Only Mode</span>
                            <span class="o_policy_title"><i class="fa fa-file-image-o text-primary me-1"></i> {record.name}</span>
                        </div>
                        <div class="o_policy_image_wrapper">
                            <img src="{preview_url}" alt="{record.name}" class="o_policy_preview_img" draggable="false" oncontextmenu="return false;"/>
                        </div>
                    </div>
                """
            # Other files / Standard Frame
            else:
                preview_url = f"/bxi_hr_policy/preview/{record.id}#toolbar=0"
                record.preview_html = f"""
                    <div class="o_policy_viewer_container" oncontextmenu="return false;">
                        <div class="o_policy_viewer_header">
                            <span class="o_policy_badge"><i class="fa fa-lock me-1"></i> View Only Mode</span>
                            <span class="o_policy_title"><i class="fa fa-file-o text-secondary me-1"></i> {record.name}</span>
                        </div>
                        <iframe src="{preview_url}" 
                                class="o_policy_pdf_frame" 
                                title="{record.name}"
                                frameborder="0">
                        </iframe>
                    </div>
                """
