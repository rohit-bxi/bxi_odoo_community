from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BxiGiftReceipt(models.Model):
    """Receipt of Gift declaration: a thing of value received from a Third Party."""
    _name = 'bxi.gift.receipt'
    _description = 'Receipt of Gift'
    _inherit = ['bxi.gift.mixin']
    _gift_sequence = 'bxi.gift.receipt'
    _gift_zone_purpose = 'receiving'
    _order = 'id desc'

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Under Review'),
        ('declared', 'Declared'),
        ('approved', 'Accepted'),
        ('to_return', 'To Return'),
        ('returned', 'Returned'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)
    partner_id = fields.Many2one('res.partner', string='Given By', required=True, tracking=True)
    item_type_id = fields.Many2one('bxi.gift.item.type', string='What', required=True)
    description = fields.Text(required=True)
    received_date = fields.Date(required=True, default=fields.Date.context_today)
    value_unknown = fields.Boolean(string='Value Unknown')
    supplier_in_tender = fields.Boolean(
        compute='_compute_supplier_in_tender', store=True, readonly=False,
        help="BXI is tendering, negotiating or otherwise in a process with this supplier.")
    solicited = fields.Boolean(string='Requested by the Employee',
                               help="Soliciting gifts is never permitted: the gift must be returned.")
    refusal_unacceptable = fields.Boolean(
        string='Accepted Because Refusal Would Embarrass',
        help="Policy exception: an unsolicited gift above the limits (or of unknown value) accepted to avoid "
             "embarrassing the Third Party. It must be reported and returned.")
    giver_year_total = fields.Float(string='Received From Giver This Year (USD)', readonly=True, copy=False,
                                    digits=(16, 2))
    outcome = fields.Selection([
        ('keep', 'Keep, no declaration needed'),
        ('declare', 'Declared for review'),
        ('return', 'Must be returned'),
    ], readonly=True, copy=False, tracking=True)
    return_due_date = fields.Date(readonly=True, copy=False)
    return_expense_id = fields.Many2one('hr.expense', string='Return Shipping Claim', copy=False)
    return_reference = fields.Char(
        string='Return Transaction ID', copy=False,
        help="Transaction ID of the claim for the return shipping charges.")
    returned_date = fields.Date(readonly=True, copy=False)
    edgefi_reference = fields.Char(
        string='EdgeFi Declaration / Transaction Reference',
        copy=False,
        tracking=True,
    )
    lso_review_state = fields.Selection([
        ('not_required', 'Not Required'),
        ('pending', 'Pending LSO Review'),
        ('reviewed', 'Reviewed'),
    ], string='LSO Review', default='not_required', copy=False, tracking=True)

    @api.depends('partner_id')
    def _compute_supplier_in_tender(self):
        for rec in self:
            rec.supplier_in_tender = rec.partner_id.gift_in_tender or rec.partner_id.commercial_partner_id.gift_in_tender

    def _gift_category(self):
        return 'receive'

    def _gift_policy_date(self):
        return self.received_date or fields.Date.context_today(self)

    def _gift_counterparty(self):
        return self.partner_id

    def _gift_threshold_value(self):
        """Cumulative value received from the same giver in the calendar year (USD)."""
        usd = self.env.ref('base.USD')
        company = self.company_id or self.env.company
        day = self._gift_policy_date()
        others = self.sudo().search([
            ('id', '!=', self.id),
            ('employee_id', '=', self.employee_id.id),
            ('partner_id.commercial_partner_id', '=', self.partner_id.commercial_partner_id.id),
            ('state', 'in', ('submitted', 'declared', 'approved', 'to_return', 'returned')),
            ('received_date', '>=', date(day.year, 1, 1)),
            ('received_date', '<=', date(day.year, 12, 31)),
        ])
        total = sum(o.currency_id._convert(o.amount, usd, company, o.received_date, round=False) for o in others)
        total += self.currency_id._convert(self.amount, usd, company, day, round=False)
        self.sudo().giver_year_total = total
        return total, usd

    def _must_return(self):
        """Reasons the gift cannot be kept, whatever its value."""
        reasons = []
        if self.item_type_id.prohibited:
            reasons.append(_("%s cannot be accepted.", self.item_type_id.name))
        if self.solicited:
            reasons.append(_("Gifts may never be solicited."))
        if self.supplier_in_tender:
            reasons.append(_("Nothing may be accepted from a supplier during a tender or negotiation."))
        if self.refusal_unacceptable:
            reasons.append(_("Accepted only to avoid embarrassment: it must be returned."))
        if self.threshold_id.outcome == 'prohibited':
            reasons.append(_("The value received from this giver this year (USD %.2f) exceeds the limit.",
                             self.giver_year_total))
        return reasons

    def _gift_check(self):
        blocking = []
        if not self.threshold_id and not self.value_unknown:
            blocking.append(_("No policy threshold is configured for this value. Contact the LSO team."))
        if not self.value_unknown and self.amount <= 0:
            blocking.append(_("Enter the estimated value, or tick 'Value Unknown'."))
        return blocking, []

    def _gift_steps(self):
        if self.value_unknown:
            return ['lso']
        return super()._gift_steps()

    def _gift_start_approval(self):
        reasons = self._must_return()
        if reasons:
            self.write({'outcome': 'return', 'policy_warning': '\n'.join(reasons)})
            self._set_to_return()
            if self.solicited:
                self.env['bxi.gift.violation'].sudo().create({
                    'violation_type': 'solicitation',
                    'subject_employee_id': self.employee_id.id,
                    'subject_partner_id': self.partner_id.id,
                    'description': _("Gift solicited, declared in %s.", self.name),
                    'related_ref': '%s,%s' % (self._name, self.id),
                })
            return
        if self.threshold_id.outcome == 'allowed' and not self.value_unknown:
            self.write({'outcome': 'keep', 'state': 'approved', 'lso_review_state': 'not_required'})
            self.message_post(body=_("Within the limit: no declaration or approval needed."))
            return
        self.outcome = 'declare'
        self.lso_review_state = 'pending'
        super()._gift_start_approval()

    def action_lso_review(self):
        self.ensure_one()
        if not self.env.user.has_group('bxi_gift_entertainment.group_gift_lso'):
            raise UserError(_("Only the LSO team can complete the review."))
        if self.state != 'declared':
            raise UserError(_("Only declared receipts can be reviewed."))
        if not self.edgefi_reference:
            raise UserError(_("Enter the EdgeFi transaction / declaration ID before completing the review."))
        self.write({'lso_review_state': 'reviewed'})
        self.message_post(body=_("LSO reviewed the declaration. EdgeFi reference: %s",
                                 self.edgefi_reference))
        return True

    def _on_gift_rejected(self, reason):
        self.write({'outcome': 'return'})
        self._set_to_return()

    def _set_to_return(self):
        days = int(self._gift_param('return_due_days', 15))
        self.write({'state': 'to_return', 'return_due_date': fields.Date.context_today(self) + timedelta(days=days)})
        self._gift_notify_employee(_(
            "%(name)s must be returned to %(giver)s by %(day)s with a covering letter (Print Return Letter), "
            "then record the transaction ID of the return shipping claim.",
            name=self.name, giver=self.partner_id.name, day=self.return_due_date))
        self._gift_notify_lso(_("Gift %s to be returned", self.name),
                              _("<p>%(employee)s must return a gift from %(giver)s: %(reasons)s</p>",
                                employee=self.employee_id.name, giver=self.partner_id.name,
                                reasons=self.policy_warning or ''))

    def action_require_return(self):
        """LSO decision during the review: the gift must be returned."""
        if not self._gift_is_officer():
            raise UserError(_("Only the LSO team can require a gift to be returned."))
        for rec in self.filtered(lambda r: r.state in ('submitted', 'approved', 'declared')):
            rec.approval_line_ids.filtered(lambda l: l.state in ('waiting', 'pending')).sudo().write(
                {'state': 'skipped'})
            rec._gift_close_activities(rec.approval_line_ids.user_ids)
            rec.sudo().write({'outcome': 'return'})
            rec.sudo()._set_to_return()
        return True

    def action_print_return_letter(self):
        return self.env.ref('bxi_gift_entertainment.action_report_gift_return_letter').report_action(self)

    def action_mark_returned(self):
        for rec in self:
            if rec.state != 'to_return':
                raise UserError(_("Only gifts to return can be marked as returned."))
            if not self.env.su and rec.employee_user_id != self.env.user and not rec._gift_is_officer():
                raise UserError(_("You can only update your own declarations."))
            reference = rec.return_reference or (rec.return_expense_id and str(rec.return_expense_id.id))
            if not reference:
                raise UserError(_("Enter the transaction ID of the return shipping claim (or link the claim)."))
            rec.sudo().write({'state': 'returned', 'returned_date': fields.Date.context_today(rec),
                              'return_reference': reference})
            rec.sudo()._gift_close_activities(rec._gift_group_users('group_gift_lso'))
            rec.message_post(body=_("Gift returned to %(giver)s (transaction %(ref)s).",
                                    giver=rec.partner_id.name, ref=reference))
        return True

    @api.model
    def _cron_overdue_returns(self):
        today = fields.Date.context_today(self)
        for rec in self.sudo().search([('state', '=', 'to_return'), ('return_due_date', '<', today)]):
            rec._gift_notify_employee(_("Reminder: %(name)s should have been returned by %(day)s.",
                                        name=rec.name, day=rec.return_due_date))
            pending = rec.activity_ids.user_id
            for user in rec._gift_group_users('group_gift_lso') - pending:
                rec.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                      summary=_("Gift return overdue: %s", rec.name))
