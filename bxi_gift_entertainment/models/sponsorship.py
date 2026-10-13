from markupsafe import Markup, escape

from odoo import _, api, fields, models

from .approval import BASE_STATES


class BxiGiftSponsorship(models.Model):
    """Sponsorship given by BXI (business marketing or charitable) or solicited from a Third Party."""
    _name = 'bxi.gift.sponsorship'
    _description = 'Sponsorship'
    _inherit = ['bxi.gift.mixin']
    _gift_sequence = 'bxi.gift.sponsorship'
    _order = 'id desc'

    state = fields.Selection(BASE_STATES, default='draft', required=True, tracking=True, copy=False)
    direction = fields.Selection([
        ('give', 'BXI Sponsors'),
        ('solicit', 'BXI Solicits Sponsorship'),
    ], required=True, default='give', tracking=True)
    sponsorship_type = fields.Selection([
        ('marketing', 'Business Marketing'),
        ('charitable', 'Charitable'),
    ], required=True, default='marketing', tracking=True)
    event_name = fields.Char(required=True)
    partner_id = fields.Many2one('res.partner', string='Organizer / Sponsor', required=True, tracking=True)
    event_date = fields.Date(required=True, default=fields.Date.context_today)
    purpose = fields.Text(required=True)
    agreement_attachment_ids = fields.Many2many(
        'ir.attachment', 'bxi_gift_sponsorship_attachment_rel', 'sponsorship_id', 'attachment_id',
        string='Agreement')
    government_attendees = fields.Boolean(
        string='Government Officials Attend',
        help="Including employees of state-owned media: the Government Official rules apply to them.")
    recipient_ids = fields.One2many('bxi.gift.sponsorship.recipient', 'sponsorship_id',
                                    string='Gifts / Entertainment to Attendees', copy=True)
    edgefi_reference = fields.Char(string='EdgeFi / Payment Reference', copy=False)

    def _gift_category(self):
        if self.direction == 'solicit':
            return 'solicit'
        return 'sponsor_charitable' if self.sponsorship_type == 'charitable' else 'sponsor_marketing'

    def _gift_policy_date(self):
        return self.event_date or fields.Date.context_today(self)

    def _gift_counterparty(self):
        return self.partner_id

    def _gift_due_diligence_scope(self):
        return 'sponsorship'

    def _gift_requires_due_diligence(self):
        return self.direction == 'solicit' or self.sponsorship_type == 'charitable'

    def _gift_steps(self):
        steps = super()._gift_steps()
        if self.government_attendees and 'l4' not in steps:
            steps.insert(0, 'l4')
        return steps

    def _government_recipient_year_total(self, recipient):
        usd = self.env.ref('base.USD')
        year = self._gift_policy_date().year
        total = 0.0
        for sponsorship in self.sudo().search([
            ('id', '!=', self.id),
            ('event_date', '>=', '%s-01-01' % year),
            ('event_date', '<=', '%s-12-31' % year),
            ('state', 'in', ('submitted', 'approved')),
        ]):
            for row in sponsorship.recipient_ids:
                if row.is_government_official and row.name == recipient.name and row.organization == recipient.organization:
                    total += row.currency_id._convert(
                        row.value, usd, sponsorship.company_id or self.env.company,
                        sponsorship.event_date, round=False)
        total += recipient.currency_id._convert(
            recipient.value, usd, self.company_id or self.env.company,
            self._gift_policy_date(), round=False)
        return total

    def _gift_check(self):
        blocking, warnings = super()._gift_check()
        if self.amount <= 0:
            blocking.append(_("Enter the sponsorship value."))
        if self.direction == 'solicit':
            if not self.employee_id._gift_is_l1_or_above():
                blocking.append(_("Sponsorship may only be solicited when requested by an L1 Head / MD or above."))
            if self.sponsorship_type != 'charitable':
                blocking.append(_("Sponsorship may only be solicited for charitable / CSR activities, college "
                                  "symposiums or technical events: record it as Charitable."))
        if self.partner_id.commercial_partner_id.gift_blacklisted:
            blocking.append(_("%s is blacklisted under the Gift and Entertainment Policy.", self.partner_id.name))
        usd = self.env.ref('base.USD')
        company = self.company_id or self.env.company
        for recipient in self.recipient_ids:
            if recipient.is_government_official:
                total = self._government_recipient_year_total(recipient)
                if total > 50:
                    blocking.append(_(
                        "%s is a Government Official: cumulative things of value may not exceed USD 50 within one year "
                        "(this sponsorship would make the total USD %.2f).",
                        recipient.name, total))
        if self.government_attendees:
            warnings.append(_("Government Officials attend: the Government Official rules apply to anything "
                              "offered to them."))
        return blocking, warnings

    def _on_gift_approved(self):
        super()._on_gift_approved()
        if self.recipient_ids or self.threshold_id.notify_lso:
            rows = Markup('').join(
                Markup('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>') % (
                    r.name, r.email or '', r.organization or '', r.reason or '')
                for r in self.recipient_ids)
            body = Markup('<p>%s</p><table border="1"><tr><th>%s</th><th>%s</th><th>%s</th><th>%s</th></tr>%s'
                          '</table>') % (
                _("Sponsorship %(name)s (%(event)s) approved.", name=self.name, event=self.event_name),
                _("Recipient"), _("E-mail"), _("Organization"), _("Reason"), rows)
            self._gift_notify_lso(_("Sponsorship %s: gifts to attendees", self.name), escape(body))


class BxiGiftSponsorshipRecipient(models.Model):
    _name = 'bxi.gift.sponsorship.recipient'
    _description = 'Sponsorship Attendee Gift'

    sponsorship_id = fields.Many2one('bxi.gift.sponsorship', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='sponsorship_id.currency_id')
    name = fields.Char(string='Recipient', required=True)
    email = fields.Char(required=True)
    organization = fields.Char(required=True)
    reason = fields.Char(string='Reason for Gift / Entertainment', required=True)
    value = fields.Monetary(currency_field='currency_id')
    is_government_official = fields.Boolean(string='Government Official')
