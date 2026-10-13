from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

CATEGORIES = [
    ('gift', 'Gift (given)'),
    ('entertainment', 'Meal / Entertainment (given, per person)'),
    ('government', 'Government Official (given, per year)'),
    ('receive', 'Received (per giver, per calendar year)'),
    ('donation', 'Donation (per financial year)'),
    ('political', 'Political Contribution'),
    ('sponsor_marketing', 'Business Marketing Sponsorship'),
    ('sponsor_charitable', 'Charitable Sponsorship'),
    ('solicit', 'Solicitation of Sponsorship'),
]
APPROVER_TYPES = [
    ('skip_manager', "Reporting Manager's Reporting Manager (minimum band)"),
    ('l4', 'L4 Head'),
    ('l3', 'L3 Head'),
    ('l2', 'L2 Head'),
    ('l1', 'L1 Head'),
    ('md', 'MD'),
    ('ceo', 'CEO'),
    ('cfo', 'CFO'),
    ('board', 'Board'),
    ('ethics_committee', 'Ethics Committee'),
    ('lso', 'LSO Team'),
    ('due_diligence', 'LSO Due Diligence'),
    ('etc', 'E&TC / General Counsel'),
    ('l3_or_manager', 'L3 Head or Reporting Manager'),
]


class BxiGiftZone(models.Model):
    """Region of the policy tables: giving (India / other countries) or receiving
    (Americas, ANZ and Europe / other countries)."""
    _name = 'bxi.gift.zone'
    _description = 'Gift Policy Region'
    _order = 'purpose, sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    purpose = fields.Selection([('giving', 'Giving'), ('receiving', 'Receiving')], required=True)
    country_ids = fields.Many2many(
        'res.country', string='Countries',
        help="Leave empty for the region that applies to every other country.")
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint('unique(code)', 'The region code must be unique.')

    @api.model
    def _seed_countries(self, code, country_codes):
        """Initial countries of a region; an administrator's later changes are kept."""
        zone = self.search([('code', '=', code)], limit=1)
        if zone and not zone.country_ids:
            zone.country_ids = self.env['res.country'].search([('code', 'in', country_codes)])

    @api.model
    def _get_zone(self, purpose, employee):
        employee = employee.sudo()
        country = employee.address_id.country_id or employee.company_id.country_id
        zones = self.search([('purpose', '=', purpose)])
        return zones.filtered(lambda z: country in z.country_ids)[:1] or zones.filtered(lambda z: not z.country_ids)[:1]


class BxiGiftItemType(models.Model):
    _name = 'bxi.gift.item.type'
    _description = 'Gift / Entertainment Item Type'
    _order = 'prohibited, sequence, name'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    prohibited = fields.Boolean(help="Can never be given or accepted under the policy.")
    prohibited_reason = fields.Char()
    is_alcohol = fields.Boolean()
    active = fields.Boolean(default=True)


class BxiGiftThreshold(models.Model):
    """One row of the policy approval matrices. Amounts are in the row currency: the value of a
    request is converted to it at the request date. ``amount_from`` is exclusive (except 0) and
    ``amount_to`` inclusive, so a shared edge belongs to the lower band."""
    _name = 'bxi.gift.threshold'
    _description = 'Gift Policy Threshold'
    _order = 'category, zone_id, amount_from'

    zone_id = fields.Many2one('bxi.gift.zone', string='Region', ondelete='restrict',
                              help="Leave empty when the row applies to every region.")
    category = fields.Selection(CATEGORIES, required=True)
    currency_id = fields.Many2one('res.currency', required=True)
    amount_from = fields.Float(string='Above', digits=(16, 2))
    amount_to = fields.Float(string='Up To', digits=(16, 2), help="0 means no upper limit.")
    outcome = fields.Selection([
        ('allowed', 'Allowed, nothing to do'),
        ('declare', 'Declare'),
        ('approve', 'Approve'),
        ('prohibited', 'Prohibited'),
    ], required=True, default='approve')
    step_ids = fields.One2many('bxi.gift.threshold.step', 'threshold_id', string='Approval Steps', copy=True)
    notify_lso = fields.Boolean(string='Inform LSO')
    date_from = fields.Date(string='Valid From')
    date_to = fields.Date(string='Valid To')
    note = fields.Char()
    active = fields.Boolean(default=True)

    @api.constrains('category', 'zone_id', 'amount_from', 'amount_to', 'date_from', 'date_to', 'active')
    def _check_overlap(self):
        for row in self.filtered('active'):
            if row.amount_to and row.amount_to <= row.amount_from:
                raise ValidationError(_("'Up To' must be greater than 'Above'."))
            others = self.search([
                ('id', '!=', row.id), ('category', '=', row.category), ('zone_id', '=', row.zone_id.id),
            ]).filtered(lambda o: (not o.date_to or not row.date_from or o.date_to >= row.date_from)
                        and (not row.date_to or not o.date_from or o.date_from <= row.date_to))
            for other in others:
                if (not other.amount_to or other.amount_to > row.amount_from) and \
                        (not row.amount_to or row.amount_to > other.amount_from):
                    raise ValidationError(_("Threshold rows of the same category and region cannot overlap."))

    def _matches(self, amount):
        self.ensure_one()
        above = amount > self.amount_from or (not self.amount_from and amount >= 0)
        return above and (not self.amount_to or amount <= self.amount_to)

    @api.model
    def _find(self, category, zone, amount, currency, company, day):
        """Return (row, amount converted to the row currency) for the value, or (empty, 0)."""
        rows = self.search([
            ('category', '=', category),
            ('zone_id', 'in', (zone.id, False)),
            '|', ('date_from', '=', False), ('date_from', '<=', day),
            '|', ('date_to', '=', False), ('date_to', '>=', day),
        ]).sorted(lambda r: not r.zone_id)
        for row in rows:
            converted = currency._convert(amount, row.currency_id, company, day, round=False)
            if row._matches(converted):
                return row, converted
        return self.browse(), 0.0


    @api.model
    def _cron_annual_policy_review(self):
        """The Ethics Committee reviews the policy at least once a year."""
        users = self.env.ref('bxi_gift_entertainment.group_gift_ethics_committee').sudo().all_user_ids.filtered(
            lambda u: u.active and not u.share and u.email)
        if users:
            self.env['mail.mail'].sudo().create({
                'subject': _("Annual review of the Gift and Entertainment Policy"),
                'body_html': _("<p>The Ethics Committee must review the Gift and Entertainment Policy and its "
                               "approval matrix at least once a year.</p>"),
                'email_to': ','.join(users.mapped('email')),
            })


class BxiGiftThresholdStep(models.Model):
    _name = 'bxi.gift.threshold.step'
    _description = 'Gift Policy Approval Step'
    _order = 'sequence, id'

    threshold_id = fields.Many2one('bxi.gift.threshold', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    approver_type = fields.Selection(APPROVER_TYPES, required=True)
