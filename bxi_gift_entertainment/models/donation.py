from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .approval import BASE_STATES


class BxiGiftDonation(models.Model):
    """Donation, charitable giving or political contribution made on behalf of BXI."""
    _name = 'bxi.gift.donation'
    _description = 'Donation / Charitable Giving'
    _inherit = ['bxi.gift.mixin']
    _gift_sequence = 'bxi.gift.donation'
    _order = 'id desc'

    state = fields.Selection(BASE_STATES + [('done', 'Paid')], default='draft', required=True, tracking=True,
                             copy=False)
    beneficiary_partner_id = fields.Many2one('res.partner', string='Beneficiary', required=True, tracking=True)
    donation_type = fields.Selection([
        ('charity', 'Charity'),
        ('csr', 'CSR Activity'),
        ('customer_charity', "Contribution to a Customer Employee's Charity"),
        ('political', 'Political Contribution'),
    ], required=True, default='charity', tracking=True)
    purpose = fields.Text(required=True)
    donation_date = fields.Date(required=True, default=fields.Date.context_today)
    personal_capacity = fields.Boolean(
        string='Made in My Personal Capacity',
        help="Donations made by employees in their individual capacity are not reimbursable.")
    fy_start = fields.Date(string='Financial Year Start', compute='_compute_fy', store=True)
    fy_end = fields.Date(string='Financial Year End', compute='_compute_fy', store=True)
    fy_total = fields.Float(string='Company Donations This FY (USD)', readonly=True, copy=False, digits=(16, 2))
    routing = fields.Selection([
        ('direct', 'Paid by BXI through EdgeFi'),
        ('reimburse', 'Paid by the employee and reimbursed'),
    ], compute='_compute_routing', store=True)
    edgefi_reference = fields.Char(string='EdgeFi / Payment Reference', copy=False)
    expense_ids = fields.One2many('hr.expense', 'donation_id', string='Expense Claims')

    @api.depends('donation_date', 'company_id')
    def _compute_fy(self):
        for rec in self:
            company = rec.company_id or self.env.company
            dates = company.compute_fiscalyear_dates(rec.donation_date or fields.Date.context_today(rec))
            rec.fy_start, rec.fy_end = dates['date_from'], dates['date_to']

    def _amount_usd(self, amount=None, currency=None, day=None):
        return (currency or self.currency_id)._convert(
            self.amount if amount is None else amount, self.env.ref('base.USD'),
            self.company_id or self.env.company, day or self.donation_date, round=False)

    @api.depends('amount', 'currency_id', 'donation_date')
    def _compute_routing(self):
        for rec in self:
            limit = float(rec._gift_param('donation_direct_pay_above', 3000))
            rec.routing = 'reimburse' if limit and rec._amount_usd() <= limit else 'direct'

    def _gift_category(self):
        return 'political' if self.donation_type == 'political' else 'donation'

    def _gift_policy_date(self):
        return self.donation_date or fields.Date.context_today(self)

    def _gift_counterparty(self):
        return self.beneficiary_partner_id

    def _gift_due_diligence_scope(self):
        return 'donation'

    def _fy_donations(self):
        return self.sudo().search([
            ('id', '!=', self.id),
            ('company_id', '=', self.company_id.id),
            ('fy_start', '=', self.fy_start),
            ('donation_type', '!=', 'political'),
            ('state', 'in', ('submitted', 'approved', 'done')),
        ])

    def _gift_threshold_value(self):
        """Donations are approved on the company's cumulative total of the financial year (USD)."""
        if self.donation_type == 'political':
            return self.amount, self.currency_id
        total = sum(d._amount_usd() for d in self._fy_donations()) + self._amount_usd()
        self.sudo().fy_total = total
        return total, self.env.ref('base.USD')

    def _gift_requires_due_diligence(self):
        return self._amount_usd() > float(self._gift_param('donation_due_diligence_above', 25))

    def _gift_check(self):
        blocking, warnings = super()._gift_check()
        if self.amount <= 0:
            blocking.append(_("Enter the donation amount."))
        if self.personal_capacity:
            blocking.append(_("Donations made in your personal capacity are not covered by BXI and are not "
                              "reimbursable."))
        single_limit = float(self._gift_param('donation_single_limit_usd', 50000))
        if self.donation_type != 'political' and self._amount_usd() > single_limit:
            blocking.append(_("A single donation may not exceed USD %s.", single_limit))
        if self.sudo().search_count([
            ('id', '!=', self.id),
            ('beneficiary_partner_id.commercial_partner_id', '=',
             self.beneficiary_partner_id.commercial_partner_id.id),
            ('fy_start', '=', self.fy_start),
            ('state', 'in', ('submitted', 'approved', 'done')),
        ], limit=1):
            blocking.append(_("%s already received a donation this financial year: donations to a person or "
                              "organization are limited to once a year.", self.beneficiary_partner_id.name))
        if self.beneficiary_partner_id.commercial_partner_id.gift_blacklisted:
            blocking.append(_("%s is blacklisted under the Gift and Entertainment Policy.",
                              self.beneficiary_partner_id.name))
        return blocking, warnings

    def action_done(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_("Only approved donations can be marked as paid."))
            if not rec._gift_is_officer() and not self.env.user.has_group('bxi_gift_entertainment.group_gift_finance'):
                raise UserError(_("Only Finance or the LSO team can mark a donation as paid."))
            if rec.routing == 'direct' and not rec.edgefi_reference:
                raise UserError(_("Enter the EdgeFi / payment reference."))
            rec.sudo().state = 'done'
        return True
