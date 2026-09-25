# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare

CONFIRMATIONS = (
    'confirm_independent_pricing',
    'confirm_no_exchange',
    'confirm_no_agreement',
    'confirm_confidentiality',
)


class AntitrustBidDeclaration(models.Model):
    """Bid owner's antitrust declaration, required before an RFP/tender bid goes out."""
    _name = 'antitrust.bid.declaration'
    _description = 'Bid / RFP Compliance Declaration'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True,
                       default=lambda self: self.env._('New'))
    lead_id = fields.Many2one('crm.lead', string='Opportunity', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(related='lead_id.company_id', store=True)
    declared_by_id = fields.Many2one('res.users', string='Declared By', required=True, readonly=True,
                                     default=lambda self: self.env.user)
    declared_date = fields.Datetime(string='Declared On', readonly=True)
    pricing_basis = fields.Text(string='Pricing Basis',
                                help="How the pricing was prepared, e.g. internal cost model and margin policy.")
    confirm_independent_pricing = fields.Boolean(
        string='Pricing and terms were determined independently by BXI Tech')
    confirm_no_exchange = fields.Boolean(
        string='No pricing, discount, margin or bid information was shared with or received from any competitor')
    confirm_no_agreement = fields.Boolean(
        string='There is no agreement or understanding with competitors about this bid, customers or territories')
    confirm_confidentiality = fields.Boolean(
        string='Price-sensitive information was shared only with the customer, under confidentiality')
    state = fields.Selection(
        [('draft', 'Draft'), ('to_approve', 'Waiting for CPO'), ('confirmed', 'Confirmed'),
         ('rejected', 'Rejected')],
        string='Status', default='draft', required=True, tracking=True, copy=False,
    )
    quotation_snapshot = fields.Json(string='Declared Quotations', readonly=True, copy=False,
                                     help="Quotation id -> total at the time of the declaration.")
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    reject_reason = fields.Text(string='Rejection Reason')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', self.env._('New')) == self.env._('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('antitrust.bid.declaration') \
                    or self.env._('New')
        return super().create(vals_list)

    def write(self, vals):
        protected = {'state', 'quotation_snapshot', 'approved_by_id', 'declared_date', 'declared_by_id', 'lead_id'}
        if not self.env.su and not self._is_cpo():
            if vals.keys() & protected:
                raise AccessError(self.env._("These fields are set by the declaration workflow."))
            if any(rec.state != 'draft' for rec in self):
                raise UserError(self.env._("A submitted declaration cannot be changed; create a new one."))
        return super().write(vals)

    @api.model
    def _is_cpo(self):
        return self.env.su or self.env.user.has_group('bxi_hr_policy.group_policy_cpo')

    @api.model
    def _snapshot(self, lead):
        orders = lead.sudo().order_ids.filtered(lambda o: o.state != 'cancel')
        return {str(order.id): order.amount_total for order in orders}

    def _matches_quotations(self):
        """True while the declared quotations are unchanged and no new one was added."""
        self.ensure_one()
        snapshot = self.quotation_snapshot or {}
        orders = self.lead_id.sudo().order_ids.filtered(lambda o: o.state != 'cancel')
        for order in orders:
            declared = snapshot.get(str(order.id))
            if declared is None or float_compare(declared, order.amount_total,
                                                 precision_rounding=order.currency_id.rounding or 0.01):
                return False
        return True

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(self.env._("Only draft declarations can be submitted."))
            if not self.env.su and rec.declared_by_id != self.env.user:
                raise AccessError(self.env._("Only the bid owner can submit the declaration."))
            if not all(rec[field] for field in CONFIRMATIONS):
                raise UserError(self.env._("All four confirmations are required."))
            needs_cpo = (rec.lead_id.company_id or self.env.company).bid_cpo_signoff
            rec.sudo().write({
                'state': 'to_approve' if needs_cpo else 'confirmed',
                'declared_date': fields.Datetime.now(),
                'quotation_snapshot': self._snapshot(rec.lead_id),
            })
            if needs_cpo:
                for user in self.env['antitrust.mixin']._cpo_users():
                    rec.sudo().activity_schedule(
                        'mail.mail_activity_data_todo', user_id=user.id,
                        summary=self.env._("Approve bid declaration %(ref)s", ref=rec.name))
        return {'type': 'ir.actions.act_window_close'}

    def action_approve(self):
        if not self._is_cpo():
            raise AccessError(self.env._("Only the CPO can approve bid declarations."))
        for rec in self:
            if rec.state != 'to_approve':
                raise UserError(self.env._("Only declarations waiting for the CPO can be approved."))
            rec.write({'state': 'confirmed', 'approved_by_id': self.env.user.id})
            rec.activity_unlink(['mail.mail_activity_data_todo'])

    def action_reject(self):
        if not self._is_cpo():
            raise AccessError(self.env._("Only the CPO can reject bid declarations."))
        for rec in self:
            if rec.state != 'to_approve':
                raise UserError(self.env._("Only declarations waiting for the CPO can be rejected."))
            if not rec.reject_reason:
                raise UserError(self.env._("Enter the reason for rejecting the declaration."))
            rec.write({'state': 'rejected', 'approved_by_id': self.env.user.id})
            rec.activity_unlink(['mail.mail_activity_data_todo'])
            rec.message_post(body=self.env._("Declaration rejected: %(reason)s", reason=rec.reject_reason),
                             partner_ids=rec.declared_by_id.partner_id.ids)
