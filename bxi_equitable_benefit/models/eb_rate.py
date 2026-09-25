from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

WORK_CATEGORY = [
    ('non_client', 'Non-Client Aligned'),
    ('client', 'Client Aligned'),
]
RATE_WORK_CATEGORY = WORK_CATEGORY + [('any', 'Non-Client or Client Aligned')]
DEPLOYMENT = [
    ('onsite', 'Onsite'),
    ('offshore', 'Offshore'),
]
RATE_DEPLOYMENT = DEPLOYMENT + [('any', 'Onsite / Offshore')]


class BxiEbRate(models.Model):
    """One row of the policy eligibility matrix.

    Rows are versioned by date so a revised policy never changes payouts
    already computed for earlier periods.
    """
    _name = 'bxi.eb.rate'
    _description = 'Equitable Benefit Rate'
    _inherit = ['mail.thread']
    _order = 'work_pattern_id, work_category, deployment, date_from desc'

    work_pattern_id = fields.Many2one('bxi.eb.work.pattern', required=True, ondelete='restrict', tracking=True)
    work_category = fields.Selection(RATE_WORK_CATEGORY, required=True, default='any', tracking=True)
    deployment = fields.Selection(RATE_DEPLOYMENT, required=True, default='any', tracking=True)
    rate_percent = fields.Float(
        string='Benefit (% of Component A)', digits=(16, 4), required=True, tracking=True)
    date_from = fields.Date(string='Valid From', required=True, default=lambda self: fields.Date.to_date('2000-01-01'),
                            tracking=True)
    date_to = fields.Date(string='Valid To', tracking=True)
    company_id = fields.Many2one('res.company', help="Leave empty to apply to all companies.")
    note = fields.Char()
    active = fields.Boolean(default=True)

    @api.constrains('rate_percent', 'date_from', 'date_to')
    def _check_values(self):
        for rate in self:
            if rate.rate_percent < 0 or rate.rate_percent > 100:
                raise ValidationError(_("The benefit percentage must be between 0 and 100."))
            if rate.date_to and rate.date_to < rate.date_from:
                raise ValidationError(_("'Valid To' cannot be before 'Valid From'."))

    @api.constrains('work_pattern_id', 'work_category', 'deployment', 'date_from', 'date_to', 'company_id', 'active')
    def _check_overlap(self):
        for rate in self.filtered('active'):
            domain = [
                ('id', '!=', rate.id),
                ('work_pattern_id', '=', rate.work_pattern_id.id),
                ('work_category', '=', rate.work_category),
                ('deployment', '=', rate.deployment),
                ('company_id', '=', rate.company_id.id),
                '|', ('date_to', '=', False), ('date_to', '>=', rate.date_from),
            ]
            if rate.date_to:
                domain.append(('date_from', '<=', rate.date_to))
            if self.search_count(domain, limit=1):
                raise ValidationError(_(
                    "Another rate for %(pattern)s already covers this category, deployment and period.",
                    pattern=rate.work_pattern_id.name))

    @api.model
    def _find_rate(self, work_pattern, work_category, deployment, date, company):
        """Return the most specific rate row valid on ``date``, or an empty recordset.

        An exact category/deployment/company beats 'any' / all companies.
        """
        candidates = self.search([
            ('work_pattern_id', '=', work_pattern.id),
            ('work_category', 'in', (work_category, 'any')),
            ('deployment', 'in', (deployment, 'any')),
            ('company_id', 'in', (company.id, False)),
            ('date_from', '<=', date),
            '|', ('date_to', '=', False), ('date_to', '>=', date),
        ])
        return candidates.sorted(lambda r: (
            r.work_category != work_category,
            r.deployment != deployment,
            not r.company_id,
        ))[:1]
