import pytz

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .deputation_dates import CALENDAR, WORKING

SALARY_APPROACH = [
    (CALENDAR, 'Calendar Days'),
    (WORKING, 'Working Days'),
]


class BxiDeputationCountryRule(models.Model):
    _name = 'bxi.deputation.country.rule'
    _description = 'Deputation Country Salary Rule'
    _order = 'country_id, effective_from desc'

    country_id = fields.Many2one('res.country', string='Host Country', required=True, index=True)
    salary_approach = fields.Selection(SALARY_APPROACH, string='Salary Approach', required=True, default=WORKING)
    effective_from = fields.Date(
        string='Effective From',
        help='Deputations arriving on or after this date use this rule. Leave empty to apply from the start.',
    )
    annual_divisor = fields.Float(
        string='Annual Gross Divisor', default=260.0, required=True,
        help='A gap day is paid as Host Annual Gross Salary divided by this number.',
    )
    calendar_id = fields.Many2one(
        'resource.calendar', string='Host Working Calendar',
        help='Weekend and public holidays of the host country. Required for the Working Days approach.',
    )
    note = fields.Text(string='Note')
    active = fields.Boolean(default=True)

    _country_effective_unique = models.Constraint(
        'unique(country_id, effective_from)',
        'There is already a rule for this country with the same effective date.',
    )

    @api.depends('country_id', 'salary_approach', 'effective_from')
    def _compute_display_name(self):
        approaches = dict(SALARY_APPROACH)
        for rule in self:
            name = '%s - %s' % (rule.country_id.name or '', approaches.get(rule.salary_approach, ''))
            if rule.effective_from:
                name += ' (from %s)' % rule.effective_from
            rule.display_name = name

    @api.constrains('salary_approach', 'calendar_id', 'annual_divisor')
    def _check_rule(self):
        for rule in self:
            if rule.salary_approach == WORKING and not rule.calendar_id:
                raise ValidationError(self.env._(
                    'A host working calendar is required for the Working Days approach (%s).', rule.country_id.name))
            if rule.annual_divisor <= 0:
                raise ValidationError(self.env._('The annual gross divisor must be greater than zero.'))

    @api.model
    def _get_rule(self, country, on_date):
        """Rule applicable to ``country`` for an arrival on ``on_date``.

        No rule means the country follows the Calendar Days approach.
        """
        if not country:
            return self.browse()
        domain = [('country_id', '=', country.id)]
        if on_date:
            domain += ['|', ('effective_from', '=', False), ('effective_from', '<=', on_date)]
        return self.search(domain, order='effective_from desc nulls last', limit=1)

    @api.model
    def _working_day_checker(self, calendar):
        """Return ``date -> bool``: a working day of ``calendar`` that is not a public holiday.

        Only holidays attached to this calendar are used, so the home company's
        public holidays do not leak into the host country.
        """
        if not calendar:
            return lambda day: day.weekday() < 5
        tz = pytz.timezone(calendar.tz or 'UTC')
        holidays = self.env['resource.calendar.leaves'].sudo().search([
            ('calendar_id', '=', calendar.id),
            ('resource_id', '=', False),
        ])
        holiday_ranges = [
            (
                pytz.utc.localize(leave.date_from).astimezone(tz).date(),
                pytz.utc.localize(leave.date_to).astimezone(tz).date(),
            )
            for leave in holidays
        ]

        def is_working_day(day):
            if not calendar._works_on_date(day):
                return False
            return not any(start <= day <= end for start, end in holiday_ranges)

        return is_working_day
