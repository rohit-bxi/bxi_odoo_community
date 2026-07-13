# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


DOCUMENT_TYPES = [
    ('gst_certificate', 'GST Certificate'),
    ('pan_card', 'PAN Card'),
    ('msme_certificate', 'MSME Certificate'),
    ('bank_details', 'Bank Details / Cancelled Cheque'),
    ('incorporation', 'Incorporation Certificate'),
    ('compliance', 'Compliance Certificate'),
    ('agreement', 'Signed Agreement'),
    ('cancelled_cheque', 'Cancelled Cheque'),
    ('declaration', 'Vendor Declaration Form'),
    ('other', 'Other'),
]


class VendorDocument(models.Model):
    _name = 'bxi.vendor.document'
    _description = 'Vendor Document'
    _inherit = ['mail.thread']
    _order = 'create_date desc'

    vendor_id = fields.Many2one('bxi.vendor', string='Vendor', required=True, ondelete='cascade')
    document_type = fields.Selection(DOCUMENT_TYPES, string='Document Type', required=True)
    document_name = fields.Char(string='Document Name', required=True)
    reference_number = fields.Char(string='Reference / Certificate No.')
    issue_date = fields.Date(string='Issue Date')
    expiry_date = fields.Date(string='Expiry Date', tracking=True)
    attachment_id = fields.Many2many(
        'ir.attachment',
        'vendor_document_attachment_rel',
        'document_id',
        'attachment_id',
        string='Uploaded File(s)',
    )
    verification_state = fields.Selection([
        ('pending', 'Pending Review'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
    ], string='Verification Status', default='pending', tracking=True)
    verified_by = fields.Many2one('res.users', string='Verified By', readonly=True)
    verified_on = fields.Datetime(string='Verified On', readonly=True)
    rejection_reason = fields.Text(string='Rejection Reason')
    remarks = fields.Text(string='Remarks')

    # Computed
    is_expired = fields.Boolean(compute='_compute_is_expired', store=True)
    days_to_expiry = fields.Integer(compute='_compute_is_expired', string='Days to Expiry')

    @api.depends('expiry_date')
    def _compute_is_expired(self):
        today = fields.Date.today()
        for rec in self:
            if rec.expiry_date:
                delta = (rec.expiry_date - today).days
                rec.days_to_expiry = delta
                rec.is_expired = delta < 0
                if delta < 0 and rec.verification_state not in ('rejected',):
                    rec.verification_state = 'expired'
            else:
                rec.is_expired = False
                rec.days_to_expiry = 0

    def action_verify(self):
        self.write({
            'verification_state': 'verified',
            'verified_by': self.env.user.id,
            'verified_on': fields.Datetime.now(),
        })

    def action_reject(self):
        self.write({'verification_state': 'rejected'})

    def name_get(self):
        result = []
        for rec in self:
            doc_type_label = dict(DOCUMENT_TYPES).get(rec.document_type, 'Document')
            result.append((rec.id, f'{doc_type_label} — {rec.vendor_id.name}'))
        return result
