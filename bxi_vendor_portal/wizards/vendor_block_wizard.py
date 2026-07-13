# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class VendorBlockWizard(models.TransientModel):
    _name = 'vendor.block.wizard'
    _description = 'Vendor Block / Reject Wizard'

    vendor_id = fields.Many2one('bxi.vendor', string='Vendor', required=True)
    action_type = fields.Selection([
        ('block', 'Block Vendor'),
        ('reject', 'Reject Vendor'),
    ], string='Action', default='block', required=True)
    reason = fields.Text(string='Reason / Remarks', required=True)

    def action_confirm(self):
        self.ensure_one()
        vendor = self.vendor_id
        if self.action_type == 'block':
            vendor.write({'state': 'blocked', 'block_reason': self.reason})
            vendor.message_post(body=_("Vendor blocked. Reason: %s") % self.reason, subtype_xmlid='mail.mt_note')
        elif self.action_type == 'reject':
            vendor.write({'state': 'rejected', 'block_reason': self.reason})
            # Mark all pending approvals as rejected
            pending = vendor.approval_ids.filtered(lambda a: a.state == 'pending')
            pending.write({
                'state': 'rejected',
                'approved_by': self.env.user.id,
                'approved_on': fields.Datetime.now(),
                'remarks': self.reason,
            })
            template = self.env.ref('bxi_vendor_portal.email_template_vendor_rejected', raise_if_not_found=False)
            if template:
                template.send_mail(vendor.id, force_send=True)
            vendor.message_post(body=_("Vendor rejected. Reason: %s") % self.reason, subtype_xmlid='mail.mt_note')
        return {'type': 'ir.actions.act_window_close'}
