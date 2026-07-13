# -*- coding: utf-8 -*-
from odoo import models, fields


class VendorApproval(models.Model):
    _name = 'bxi.vendor.approval'
    _description = 'Vendor Approval Record'
    _order = 'create_date desc'

    vendor_id = fields.Many2one('bxi.vendor', string='Vendor', required=True, ondelete='cascade')
    level = fields.Selection([
        ('l1', 'L1 — Department Manager'),
        ('l2', 'L2 — Finance / Procurement Head'),
        ('l3', 'L3 — Director / CFO'),
    ], string='Approval Level', required=True)
    state = fields.Selection([
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Status', default='pending')
    assigned_to = fields.Many2one('res.users', string='Assigned Approver')
    approved_by = fields.Many2one('res.users', string='Actioned By')
    approved_on = fields.Datetime(string='Actioned On')
    remarks = fields.Text(string='Approver Remarks')

    def name_get(self):
        result = []
        for rec in self:
            level_label = dict(self._fields['level'].selection).get(rec.level, rec.level)
            result.append((rec.id, f'{level_label} — {rec.vendor_id.name}'))
        return result
