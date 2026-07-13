# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class VendorAsn(models.Model):
    _name = 'bxi.vendor.asn'
    _description = 'Advance Shipment Notification (ASN)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'asn_number'
    _order = 'asn_number desc'

    asn_number = fields.Char(string='ASN Number', readonly=True, copy=False, default='New')
    vendor_id = fields.Many2one('bxi.vendor', string='Vendor', required=True, tracking=True)
    partner_id = fields.Many2one(related='vendor_id.partner_id', string='Vendor Contact', store=True)
    purchase_order_id = fields.Many2one('purchase.order', string='Linked Purchase Order', tracking=True)
    po_date = fields.Datetime(related='purchase_order_id.date_approve', string='PO Date', store=True)

    # ── Transport Details ─────────────────────────────────────────────────────
    transporter_name = fields.Char(string='Transporter Name')
    vehicle_number = fields.Char(string='Vehicle Number')
    lr_number = fields.Char(string='LR / Docket Number')
    lr_date = fields.Date(string='LR Date')
    dispatch_date = fields.Date(string='Dispatch Date', tracking=True)
    expected_delivery_date = fields.Date(string='Expected Delivery Date', tracking=True)
    actual_delivery_date = fields.Date(string='Actual Delivery Date')

    # ── Delivery Lead Time ─────────────────────────────────────────────────────
    delivery_lead_days = fields.Integer(
        string='Lead Time (Days)',
        compute='_compute_lead_time',
        store=True,
    )
    is_delayed = fields.Boolean(compute='_compute_lead_time', store=True, string='Delayed?')

    # ── Barcode / QR ──────────────────────────────────────────────────────────
    barcode = fields.Char(string='Barcode / QR Reference')

    # ── State ─────────────────────────────────────────────────────────────────
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('dispatched', 'Dispatched'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, copy=False)

    is_partial = fields.Boolean(string='Partial Shipment')
    notes = fields.Text(string='Remarks / Instructions')
    asn_lines = fields.One2many('bxi.vendor.asn.line', 'asn_id', string='ASN Lines')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.ref('base.INR', raise_if_not_found=False))
    total_qty = fields.Float(compute='_compute_totals', string='Total Qty', store=True)
    total_value = fields.Monetary(compute='_compute_totals', string='Total Value', store=True, currency_field='currency_id')

    @api.depends('dispatch_date', 'expected_delivery_date', 'actual_delivery_date')
    def _compute_lead_time(self):
        for rec in self:
            if rec.dispatch_date and rec.actual_delivery_date:
                rec.delivery_lead_days = (rec.actual_delivery_date - rec.dispatch_date).days
                if rec.expected_delivery_date:
                    rec.is_delayed = rec.actual_delivery_date > rec.expected_delivery_date
                else:
                    rec.is_delayed = False
            elif rec.dispatch_date and rec.expected_delivery_date:
                from datetime import date
                today = date.today()
                rec.delivery_lead_days = (today - rec.dispatch_date).days
                rec.is_delayed = today > rec.expected_delivery_date
            else:
                rec.delivery_lead_days = 0
                rec.is_delayed = False

    @api.depends('asn_lines.qty', 'asn_lines.unit_price')
    def _compute_totals(self):
        for rec in self:
            rec.total_qty = sum(l.qty for l in rec.asn_lines)
            rec.total_value = sum(l.qty * l.unit_price for l in rec.asn_lines)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('asn_number', 'New') == 'New':
                vals['asn_number'] = self.env['ir.sequence'].next_by_code('bxi.vendor.asn.sequence') or 'ASN/NEW'
        return super().create(vals_list)

    def action_confirm(self):
        self._check_lines()
        self.state = 'confirmed'
        self.message_post(body=_("ASN confirmed."), subtype_xmlid='mail.mt_note')

    def action_dispatch(self):
        self._check_lines()
        if not self.dispatch_date:
            self.dispatch_date = fields.Date.today()
        self.state = 'dispatched'
        self.message_post(body=_("Goods dispatched."), subtype_xmlid='mail.mt_note')

    def action_deliver(self):
        if not self.actual_delivery_date:
            self.actual_delivery_date = fields.Date.today()
        self.state = 'delivered'
        self.message_post(body=_("Delivery completed."), subtype_xmlid='mail.mt_note')

    def action_cancel(self):
        self.state = 'cancelled'
        self.message_post(body=_("ASN cancelled."), subtype_xmlid='mail.mt_note')

    def action_reset_draft(self):
        self.state = 'draft'

    def _check_lines(self):
        for rec in self:
            if not rec.asn_lines:
                raise UserError(_("Please add at least one item line before confirming the ASN."))
