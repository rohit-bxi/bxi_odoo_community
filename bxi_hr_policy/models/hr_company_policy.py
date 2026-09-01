# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import mimetypes


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
        required=True,
        attachment=True,
        help='Upload the policy file (PDF, Word, or Image).'
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
