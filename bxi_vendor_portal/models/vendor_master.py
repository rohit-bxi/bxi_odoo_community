# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import re


class BxiVendor(models.Model):
    _name = 'bxi.vendor'
    _description = 'Vendor Master'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'vendor_code desc'

    # ── Identity ─────────────────────────────────────────────────────────────
    name = fields.Char(string='Vendor Name', required=True, tracking=True)
    vendor_code = fields.Char(
        string='Vendor Code',
        readonly=True,
        copy=False,
        default='Draft',
    )
    vendor_type = fields.Selection([
        ('goods', 'Goods Supplier'),
        ('service', 'Service Provider'),
        ('works', 'Works Contractor'),
        ('both', 'Goods & Services'),
    ], string='Vendor Type', default='goods', required=True, tracking=True)
    category_id = fields.Many2one('bxi.vendor.category', string='Vendor Category', tracking=True)
    company_type = fields.Selection([
        ('company', 'Company'),
        ('individual', 'Individual / Proprietorship'),
        ('partnership', 'Partnership'),
        ('llp', 'LLP'),
        ('public', 'Public Limited'),
    ], string='Company Type', default='company', required=True)

    # ── Contact ──────────────────────────────────────────────────────────────
    email = fields.Char(string='Email', tracking=True)
    phone = fields.Char(string='Phone')
    mobile = fields.Char(string='Mobile')
    website = fields.Char(string='Website')
    street = fields.Char(string='Street')
    street2 = fields.Char(string='Street 2')
    city = fields.Char(string='City')
    state_id = fields.Many2one('res.country.state', string='State')
    zip = fields.Char(string='PIN Code')
    country_id = fields.Many2one('res.country', string='Country', default=lambda self: self.env.ref('base.in', raise_if_not_found=False))

    # ── Tax & Compliance ─────────────────────────────────────────────────────
    gstin = fields.Char(string='GSTIN', size=15, tracking=True)
    pan = fields.Char(string='PAN Number', size=10, tracking=True)
    msme_registered = fields.Boolean(string='MSME Registered', tracking=True)
    msme_number = fields.Char(string='MSME Registration No.')
    msme_category = fields.Selection([
        ('micro', 'Micro Enterprise'),
        ('small', 'Small Enterprise'),
        ('medium', 'Medium Enterprise'),
    ], string='MSME Category')
    tds_applicable = fields.Boolean(string='TDS Applicable', default=True)
    tds_section = fields.Char(string='TDS Section')
    tds_rate = fields.Float(string='TDS Rate (%)', digits=(5, 2))
    gst_treatment = fields.Selection([
        ('regular', 'Regular'),
        ('composition', 'Composition'),
        ('unregistered', 'Unregistered'),
        ('sez', 'SEZ Unit'),
        ('overseas', 'Overseas'),
        ('exempt', 'Exempt'),
    ], string='GST Treatment', default='regular')

    # ── Bank Details ─────────────────────────────────────────────────────────
    bank_name = fields.Char(string='Bank Name')
    bank_account_number = fields.Char(string='Account Number')
    bank_ifsc = fields.Char(string='IFSC Code', size=11)
    bank_branch = fields.Char(string='Branch Name')
    bank_account_type = fields.Selection([
        ('savings', 'Savings'),
        ('current', 'Current'),
        ('cc', 'Cash Credit'),
    ], string='Account Type', default='current')

    # ── Payment & Terms ───────────────────────────────────────────────────────
    payment_term_id = fields.Many2one('account.payment.term', string='Payment Terms')
    currency_id = fields.Many2one('res.currency', string='Currency', default=lambda self: self.env.ref('base.INR', raise_if_not_found=False))
    credit_limit = fields.Monetary(string='Credit Limit', currency_field='currency_id')

    # ── AVL Management ───────────────────────────────────────────────────────
    is_avl = fields.Boolean(string='On Approved Vendor List (AVL)', tracking=True)
    avl_date = fields.Date(string='AVL Approved Date')
    avl_expiry = fields.Date(string='AVL Expiry Date')
    avl_remarks = fields.Text(string='AVL Remarks')

    # ── Linked res.partner ────────────────────────────────────────────────────
    partner_id = fields.Many2one('res.partner', string='Linked Contact', readonly=True)

    # ── Workflow State ────────────────────────────────────────────────────────
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted for Approval'),
        ('l1_approved', 'L1 Approved'),
        ('l2_approved', 'L2 Approved'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('blocked', 'Blocked'),
    ], string='Status', default='draft', tracking=True, copy=False)

    block_reason = fields.Text(string='Block / Rejection Reason')

    # ── Relations ─────────────────────────────────────────────────────────────
    document_ids = fields.One2many('bxi.vendor.document', 'vendor_id', string='Documents')
    approval_ids = fields.One2many('bxi.vendor.approval', 'vendor_id', string='Approval History')
    asn_ids = fields.One2many('bxi.vendor.asn', 'vendor_id', string='Shipment Notifications')
    performance_rating_ids = fields.One2many('bxi.vendor.rating', 'vendor_id', string='Performance Ratings')

    # ── Computed ──────────────────────────────────────────────────────────────
    document_count = fields.Integer(compute='_compute_document_count', string='Documents')
    asn_count = fields.Integer(compute='_compute_asn_count', string='ASNs')
    po_count = fields.Integer(compute='_compute_po_count', string='Purchase Orders')
    rating_score = fields.Float(compute='_compute_rating_score', string='Rating Score', digits=(5, 1))

    # ── Notes ─────────────────────────────────────────────────────────────────
    internal_notes = fields.Html(string='Internal Notes')
    registration_date = fields.Date(string='Registration Date', default=fields.Date.today)

    def _compute_document_count(self):
        for rec in self:
            rec.document_count = len(rec.document_ids)

    def _compute_asn_count(self):
        for rec in self:
            rec.asn_count = len(rec.asn_ids)

    def _compute_po_count(self):
        for rec in self:
            if rec.partner_id:
                rec.po_count = self.env['purchase.order'].search_count([('partner_id', '=', rec.partner_id.id)])
            else:
                rec.po_count = 0

    def _compute_rating_score(self):
        for rec in self:
            latest_rating = self.env['bxi.vendor.rating'].search([('vendor_id', '=', rec.id)], order='period_end desc', limit=1)
            rec.rating_score = latest_rating.overall_score if latest_rating else 0.0

    # ── Constraints ───────────────────────────────────────────────────────────
    @api.constrains('gstin')
    def _check_gstin(self):
        for rec in self:
            if rec.gstin:
                pattern = r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$'
                if not re.match(pattern, rec.gstin):
                    raise ValidationError(_("GSTIN '%s' is not in the correct 15-character format.") % rec.gstin)

    @api.constrains('pan')
    def _check_pan(self):
        for rec in self:
            if rec.pan:
                pattern = r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$'
                if not re.match(pattern, rec.pan.upper()):
                    raise ValidationError(_("PAN '%s' must be in the format AAAAA9999A.") % rec.pan)

    # ── Business Logic ─────────────────────────────────────────────────────────
    def action_submit_for_approval(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Only Draft vendors can be submitted for approval."))
        # Auto-generate vendor code
        if self.vendor_code == 'Draft':
            sequence = self.env['ir.sequence'].next_by_code('bxi.vendor.sequence')
            self.vendor_code = sequence
        self.state = 'submitted'
        # Create L1 approval record
        self.env['bxi.vendor.approval'].create({
            'vendor_id': self.id,
            'level': 'l1',
            'state': 'pending',
        })
        # Send notification email
        template = self.env.ref('bxi_vendor_portal.email_template_vendor_submitted', raise_if_not_found=False)
        if template:
            template.send_mail(self.id, force_send=True)
        self.message_post(body=_("Vendor submitted for L1 approval."), subtype_xmlid='mail.mt_note')

    def action_l1_approve(self):
        self.ensure_one()
        pending = self.approval_ids.filtered(lambda a: a.level == 'l1' and a.state == 'pending')
        if pending:
            pending.write({'state': 'approved', 'approved_by': self.env.user.id, 'approved_on': fields.Datetime.now()})
        self.state = 'l1_approved'
        self.env['bxi.vendor.approval'].create({
            'vendor_id': self.id,
            'level': 'l2',
            'state': 'pending',
        })
        self.message_post(body=_("L1 Approval granted."), subtype_xmlid='mail.mt_note')

    def action_l2_approve(self):
        self.ensure_one()
        pending = self.approval_ids.filtered(lambda a: a.level == 'l2' and a.state == 'pending')
        if pending:
            pending.write({'state': 'approved', 'approved_by': self.env.user.id, 'approved_on': fields.Datetime.now()})
        self.state = 'l2_approved'
        self.env['bxi.vendor.approval'].create({
            'vendor_id': self.id,
            'level': 'l3',
            'state': 'pending',
        })
        self.message_post(body=_("L2 Approval granted."), subtype_xmlid='mail.mt_note')

    def action_final_approve(self):
        self.ensure_one()
        pending = self.approval_ids.filtered(lambda a: a.level == 'l3' and a.state == 'pending')
        if pending:
            pending.write({'state': 'approved', 'approved_by': self.env.user.id, 'approved_on': fields.Datetime.now()})
        self.state = 'approved'
        # Create linked res.partner
        if not self.partner_id:
            partner = self.env['res.partner'].create({
                'name': self.name,
                'supplier_rank': 1,
                'email': self.email,
                'phone': self.phone,
                'street': self.street,
                'city': self.city,
                'state_id': self.state_id.id,
                'zip': self.zip,
                'country_id': self.country_id.id,
                'vat': self.gstin,
                'property_payment_term_id': self.payment_term_id.id,
            })
            self.partner_id = partner.id
        template = self.env.ref('bxi_vendor_portal.email_template_vendor_approved', raise_if_not_found=False)
        if template:
            template.send_mail(self.id, force_send=True)
        self.message_post(body=_("Vendor fully approved. Partner record created."), subtype_xmlid='mail.mt_note')

    def action_reject(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reject Vendor',
            'res_model': 'vendor.block.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_vendor_id': self.id, 'default_action_type': 'reject'},
        }

    def action_activate(self):
        self.ensure_one()
        if self.state not in ('approved', 'inactive'):
            raise UserError(_("Only Approved or Inactive vendors can be activated."))
        self.state = 'active'
        self.message_post(body=_("Vendor activated."), subtype_xmlid='mail.mt_note')

    def action_deactivate(self):
        self.ensure_one()
        self.state = 'inactive'
        self.message_post(body=_("Vendor deactivated."), subtype_xmlid='mail.mt_note')

    def action_block(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Block Vendor',
            'res_model': 'vendor.block.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_vendor_id': self.id, 'default_action_type': 'block'},
        }

    def action_view_documents(self):
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} — Documents',
            'res_model': 'bxi.vendor.document',
            'view_mode': 'list,form',
            'domain': [('vendor_id', '=', self.id)],
            'context': {'default_vendor_id': self.id},
        }

    def action_view_asns(self):
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} — ASNs',
            'res_model': 'bxi.vendor.asn',
            'view_mode': 'list,form',
            'domain': [('vendor_id', '=', self.id)],
            'context': {'default_vendor_id': self.id},
        }

    def action_view_purchase_orders(self):
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} — Purchase Orders',
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.partner_id.id)] if self.partner_id else [('id', '=', False)],
        }

    @api.model
    def get_vendor_dashboard_data(self):
        """Returns aggregated data for the OWL vendor analytics dashboard."""
        all_vendors = self.search([])
        total = len(all_vendors)
        by_state = {
            'draft': len(all_vendors.filtered(lambda v: v.state == 'draft')),
            'pending': len(all_vendors.filtered(lambda v: v.state in ('submitted', 'l1_approved', 'l2_approved'))),
            'active': len(all_vendors.filtered(lambda v: v.state == 'active')),
            'approved': len(all_vendors.filtered(lambda v: v.state == 'approved')),
            'inactive': len(all_vendors.filtered(lambda v: v.state == 'inactive')),
            'blocked': len(all_vendors.filtered(lambda v: v.state == 'blocked')),
        }

        # Pending approvals
        pending_approvals = self.env['bxi.vendor.approval'].search([('state', '=', 'pending')])
        by_level = {
            'l1': len(pending_approvals.filtered(lambda a: a.level == 'l1')),
            'l2': len(pending_approvals.filtered(lambda a: a.level == 'l2')),
            'l3': len(pending_approvals.filtered(lambda a: a.level == 'l3')),
        }

        # ASN stats
        all_asns = self.env['bxi.vendor.asn'].search([])
        asn_by_state = {
            'draft': len(all_asns.filtered(lambda a: a.state == 'draft')),
            'confirmed': len(all_asns.filtered(lambda a: a.state == 'confirmed')),
            'dispatched': len(all_asns.filtered(lambda a: a.state == 'dispatched')),
            'delivered': len(all_asns.filtered(lambda a: a.state == 'delivered')),
            'cancelled': len(all_asns.filtered(lambda a: a.state == 'cancelled')),
        }

        # Category breakdown
        categories = self.env['bxi.vendor.category'].search([])
        cat_data = [{
            'name': c.name,
            'count': self.search_count([('category_id', '=', c.id)])
        } for c in categories if self.search_count([('category_id', '=', c.id)]) > 0]

        # Top vendors by rating
        top_vendors = self.env['bxi.vendor.rating'].search([], order='overall_score desc', limit=10)
        top_vendor_data = [{
            'name': r.vendor_id.name,
            'code': r.vendor_id.vendor_code,
            'score': r.overall_score,
            'rating': r.rating_label,
        } for r in top_vendors]

        # Document expiry alerts
        from datetime import date, timedelta
        today = date.today()
        expiring_soon = self.env['bxi.vendor.document'].search([
            ('expiry_date', '<=', today + timedelta(days=30)),
            ('expiry_date', '>=', today),
        ])
        expired = self.env['bxi.vendor.document'].search([
            ('expiry_date', '<', today),
        ])

        return {
            'total_vendors': total,
            'by_state': by_state,
            'pending_approvals': by_level,
            'asn_stats': asn_by_state,
            'total_asns': len(all_asns),
            'categories': cat_data,
            'top_vendors': top_vendor_data,
            'expiring_documents': len(expiring_soon),
            'expired_documents': len(expired),
            'avl_vendors': len(all_vendors.filtered(lambda v: v.is_avl)),
        }
