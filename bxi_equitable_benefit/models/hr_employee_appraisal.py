from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

from .eb_eligibility import RATINGS

# Letters that carry a revised salary structure (the appraisal details page of the form).
SALARY_LETTER_TYPES = ('appraisal_letter', 'appraisal_promotion_letter', 'promotion_letter')


class HrEmployeeAppraisal(models.Model):
    """Released appraisals feed the Equitable Benefit: the performance rating of the
    year under review and the revised Annualized Component A."""
    _inherit = 'hr.employee.appraisal'

    eb_rating = fields.Selection(
        RATINGS, string='Performance Rating', tracking=True,
        help="Copied to the Equitable Benefit performance ratings when the appraisal is released.")
    eb_rating_fy_start = fields.Date(
        string='Rated Financial Year Start', compute='_compute_eb_rating_fy_start', store=True, readonly=False,
        help="Financial year the rating is for: by default the year before the one the appraisal takes "
             "effect in.")

    @api.depends('effective_date', 'release_date')
    def _compute_eb_rating_fy_start(self):
        Payout = self.env['bxi.eb.payout']
        for rec in self:
            day = rec.effective_date or rec.release_date
            rec.eb_rating_fy_start = day and Payout._get_fy_bounds(day)[0] - relativedelta(years=1)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered(lambda r: r.state == 'released')._eb_sync_released()
        return records

    def write(self, vals):
        released_before = self.filtered(lambda r: r.state == 'released')
        res = super().write(vals)
        released = self.filtered(lambda r: r.state == 'released')
        (released - released_before)._eb_sync_released()
        if {'eb_rating', 'eb_rating_fy_start'} & set(vals):
            (released & released_before)._eb_sync_rating()
        return res

    def _eb_sync_released(self):
        self._eb_sync_rating()
        self._eb_sync_component_a()

    def _eb_sync_rating(self):
        Rating = self.env['bxi.eb.performance.rating'].sudo()
        for rec in self.filtered(lambda r: r.eb_rating and r.eb_rating_fy_start):
            fy_start = self.env['bxi.eb.payout']._get_fy_bounds(rec.eb_rating_fy_start)[0]
            rating = Rating.search([('employee_id', '=', rec.employee_id.id), ('fy_start', '=', fy_start)], limit=1)
            vals = {'rating': rec.eb_rating, 'appraisal_id': rec.id}
            if rating:
                rating.write(vals)
            else:
                Rating.create(dict(vals, employee_id=rec.employee_id.id, fy_start=fy_start))

    def _eb_sync_component_a(self):
        """The new annual fixed pay (Basic + Flexible Allowance, annualized) is Component A."""
        for rec in self.filtered(lambda r: r.letter_type in SALARY_LETTER_TYPES and r.annual_fixed > 0):
            day = rec.effective_date or rec.release_date or fields.Date.context_today(rec)
            rec.employee_id._eb_set_component_a(day, rec.annual_fixed)
            rec.sudo().message_post(body=_(
                "Annualized Component A of %(employee)s set to %(amount)s from %(day)s for the Equitable "
                "Benefit.", employee=rec.employee_id.name,
                amount=rec.company_currency_id.format(rec.annual_fixed), day=day))
