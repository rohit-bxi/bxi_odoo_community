from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .approval import BASE_STATES

REQUEST_TYPES = [
    ('gift', 'Gift'),
    ('entertainment', 'Meal / Entertainment'),
    ('travel', 'Business Travel'),
    ('seasonal', 'Seasonal / Holiday Gift'),
    ('prize', 'Prize / Award / Raffle'),
]
CERTIFICATION = (
    "I certify that the information above is true and correct. I further certify that I am familiar with "
    "BXI's ABAC, COBEC, BGEP and all other applicable BXI policies, that this complies with BXI's policies and "
    "applicable laws, and that I have no knowledge or information suggesting that the gift will be used for a "
    "corrupt purpose or for any purpose other than the one stated herein."
)


class BxiGiftRequest(models.Model):
    """Gift Request / Entertainment Information: giving a thing of value to a Third Party."""
    _name = 'bxi.gift.request'
    _description = 'Gift / Entertainment Request'
    _inherit = ['bxi.gift.mixin']
    _gift_sequence = 'bxi.gift.request'
    _order = 'id desc'

    state = fields.Selection(BASE_STATES + [('done', 'Done')], default='draft', required=True, tracking=True,
                             copy=False)
    request_type = fields.Selection(REQUEST_TYPES, required=True, default='gift', tracking=True)
    approved_marketing_event = fields.Boolean(
        string='BXI-Approved Marketing Event / Campaign',
        help='Required for prizes, awards and raffle items offered as part of an approved marketing event/campaign.',
    )
    item_type_id = fields.Many2one('bxi.gift.item.type', string='What', required=True)
    partner_id = fields.Many2one('res.partner', string='Third Party', required=True, tracking=True,
                                 help="Customer, supplier, dealer, vendor or other organization / person.")
    recipient_name = fields.Char(required=True)
    recipient_email = fields.Char()
    recipient_designation = fields.Char()
    recipient_organization = fields.Char(compute='_compute_recipient_organization', store=True, readonly=False)
    is_government_official = fields.Boolean(
        string='Government Official', compute='_compute_is_government_official', store=True, readonly=False,
        help="Includes family members of officials and employees of state-owned or state-controlled entities.")
    event_date = fields.Date(string='Gift / Event Date', required=True, default=fields.Date.context_today)
    late_submission = fields.Boolean(readonly=True, copy=False)
    purpose = fields.Text(string='Business Purpose', required=True)
    is_branded = fields.Boolean(string='BXI Branded / Promotional')
    includes_alcohol = fields.Boolean()
    via_intermediary = fields.Boolean(
        string='Given Through an Intermediary',
        help="Dealer, vendor, broker, clearing agent, consultant or travel agent offering it on BXI's behalf.")
    employer_allows = fields.Boolean(
        string="Recipient's Employer Allows It", default=True,
        help="Untick when the Third Party said it may not accept, or its employer does not allow it.")
    attendee_ids = fields.One2many('bxi.gift.request.attendee', 'request_id', string='Attendees', copy=True)
    attendee_count = fields.Integer(compute='_compute_per_person', store=True)
    amount_per_person = fields.Monetary(compute='_compute_per_person', store=True, currency_field='currency_id')
    government_year_total = fields.Float(
        string='Year Total to the Official (USD)', readonly=True, copy=False, digits=(16, 2))
    certification = fields.Boolean(string='I Certify', help=CERTIFICATION)
    certification_text = fields.Text(default=CERTIFICATION, readonly=True)
    actual_amount = fields.Monetary(currency_field='currency_id', copy=False, tracking=True)
    expense_ids = fields.One2many('hr.expense', 'gift_request_id', string='Expense Claims')

    @api.depends('partner_id')
    def _compute_recipient_organization(self):
        for rec in self:
            rec.recipient_organization = rec.partner_id.commercial_partner_id.name

    @api.depends('partner_id')
    def _compute_is_government_official(self):
        for rec in self:
            partner = rec.partner_id
            rec.is_government_official = partner.gift_government_official \
                or partner.commercial_partner_id.gift_government_official

    @api.depends('amount', 'attendee_ids', 'request_type')
    def _compute_per_person(self):
        for rec in self:
            count = len(rec.attendee_ids) if rec.request_type == 'entertainment' else 0
            rec.attendee_count = count
            rec.amount_per_person = rec.amount / count if count else rec.amount

    # ------------------------------------------------------------------
    # Policy
    # ------------------------------------------------------------------
    def _gift_category(self):
        if self.is_government_official:
            return 'government'
        return 'entertainment' if self.request_type == 'entertainment' else 'gift'

    def _gift_policy_date(self):
        return self.event_date or fields.Date.context_today(self)

    def _to_usd(self, amount, currency, day):
        usd = self.env.ref('base.USD')
        return currency._convert(amount, usd, self.company_id or self.env.company, day, round=False)

    def _government_year_total(self):
        """Value given to the official's organization in the calendar year, this request included (USD)."""
        day = self._gift_policy_date()
        others = self.search([
            ('id', '!=', self.id),
            ('is_government_official', '=', True),
            ('partner_id', '=', self.partner_id.id),
            ('state', 'in', ('submitted', 'approved', 'done')),
            ('event_date', '>=', date(day.year, 1, 1)),
            ('event_date', '<=', date(day.year, 12, 31)),
        ])
        total = sum(other._to_usd(other.actual_amount or other.amount, other.currency_id, other.event_date)
                    for other in others.sudo())
        return total + self._to_usd(self.amount, self.currency_id, day)

    def _gift_threshold_value(self):
        if self.is_government_official:
            total = self._government_year_total()
            self.sudo().government_year_total = total
            return total, self.env.ref('base.USD')
        if self.request_type == 'entertainment':
            return self.amount_per_person, self.currency_id
        return self.amount, self.currency_id

    def _gift_counterparty(self):
        return self.partner_id

    def _gift_check(self):
        blocking, warnings = super()._gift_check()
        partner = self.partner_id.commercial_partner_id
        today = fields.Date.context_today(self)
        if self.amount <= 0:
            blocking.append(_("Enter the value of the gift or entertainment."))
        if self.item_type_id.prohibited:
            blocking.append(_("%(item)s can never be given: %(reason)s", item=self.item_type_id.name,
                              reason=self.item_type_id.prohibited_reason or _("prohibited by the policy")))
        if self.request_type == 'prize' and not self.approved_marketing_event:
            blocking.append(_(
                "Prize / award / raffle items may only be offered as part of a BXI-approved marketing event or campaign."
            ))
        if partner.gift_blacklisted or self.partner_id.gift_blacklisted:
            blocking.append(_("%s is blacklisted under the Gift and Entertainment Policy.", partner.name))
        if partner.gift_in_tender or self.partner_id.gift_in_tender:
            blocking.append(_("BXI is tendering to or negotiating with %s: no gift may be offered during the "
                              "process.", partner.name))
        if self.via_intermediary:
            blocking.append(_("Gifts may not be offered through intermediaries (dealers, vendors, brokers, "
                              "agents, consultants)."))
        if not self.employer_allows:
            blocking.append(_("The recipient's employer does not allow it: the restriction must be respected."))
        if self.request_type == 'entertainment' and not self.attendee_ids:
            blocking.append(_("List the attendees: entertainment limits apply per person."))
        if self.request_type == 'seasonal':
            limit = float(self._gift_param('seasonal_limit_usd', 250))
            if self._to_usd(self.amount, self.currency_id, self._gift_policy_date()) > limit:
                blocking.append(_("Seasonal gift boxes may not exceed USD %s (excluding packing and shipping).",
                                  limit))
        if self.event_date and self.event_date < today:
            india = self.zone_id.code == 'GIVE_IN'
            if self.request_type != 'entertainment' or india:
                blocking.append(_("The request must be submitted before the gift or event date."))
            else:
                warnings.append(_("Entertainment Information submitted after the event."))
        if not self.certification:
            blocking.append(_("Tick the certification before submitting."))
        if self.is_government_official and self.threshold_id.outcome == 'prohibited':
            blocking.append(_("Things of value to a Government Official are limited to USD 50 a year "
                              "(USD %.2f with this request).", self.government_year_total))
        if self.includes_alcohol:
            warnings.append(_("Alcohol: the expense claim needs the approval of the L3 Head or reporting manager."))
        if self.request_type in ('gift', 'seasonal') and not self.is_branded:
            warnings.append(_("Gifts should generally be BXI-branded or promotional rather than personal."))
        return blocking, warnings

    def action_submit(self):
        for rec in self:
            rec.sudo().late_submission = bool(rec.event_date and rec.event_date < fields.Date.context_today(rec))
        return super().action_submit()

    def _on_gift_approved(self):
        super()._on_gift_approved()
        if self.threshold_id.notify_lso:
            self._gift_notify_lso(
                _("Gift Request %s approved", self.name),
                _("<p>%(employee)s: %(type)s for %(recipient)s (%(org)s, %(email)s), value %(amount)s.</p>",
                  employee=self.employee_id.name, type=dict(REQUEST_TYPES)[self.request_type],
                  recipient=self.recipient_name, org=self.recipient_organization or '',
                  email=self.recipient_email or '', amount=self.currency_id.format(self.amount)))

    def action_done(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_("Only approved requests can be marked as done."))
            if not self.env.su and rec.employee_user_id != self.env.user and not rec._gift_is_officer():
                raise UserError(_("You can only close your own requests."))
            rec.sudo().write({'state': 'done', 'actual_amount': rec.actual_amount or rec.amount})
        return True


class BxiGiftRequestAttendee(models.Model):
    _name = 'bxi.gift.request.attendee'
    _description = 'Entertainment Attendee'

    request_id = fields.Many2one('bxi.gift.request', required=True, ondelete='cascade')
    name = fields.Char(string='Full Name', required=True)
    designation = fields.Char(required=True)
    organization = fields.Char()
    attendee_type = fields.Selection([('bxi', 'BXI'), ('external', 'Third Party')], default='external',
                                     required=True)
