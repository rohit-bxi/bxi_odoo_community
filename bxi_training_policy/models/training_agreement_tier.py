from odoo import api, fields, models
from odoo.exceptions import ValidationError


class BxiTrainingAgreementTier(models.Model):
    """Service period required by the consolidated cost of a training."""
    _name = 'bxi.training.agreement.tier'
    _description = 'Training Service Agreement Tier'
    _order = 'min_amount'
    _rec_name = 'months'

    min_amount = fields.Float(string='From Amount', required=True)
    max_amount = fields.Float(string='To Amount', help="0 means no upper limit.")
    months = fields.Integer(string='Service Period (Months)', required=True)
    company_id = fields.Many2one('res.company', string='Company', help="Empty: applies to every company.")
    note = fields.Char(string='Note')
    active = fields.Boolean(default=True)

    @api.constrains('min_amount', 'max_amount', 'months', 'company_id', 'active')
    def _check_tier(self):
        for tier in self:
            if tier.months <= 0:
                raise ValidationError(self.env._("The service period must be at least one month."))
            if tier.max_amount and tier.max_amount < tier.min_amount:
                raise ValidationError(self.env._("The upper amount must be greater than the lower amount."))
            others = self.search([
                ('id', '!=', tier.id), ('company_id', '=', tier.company_id.id), ('active', '=', True),
            ])
            upper = tier.max_amount or float('inf')
            for other in others:
                if tier.min_amount <= (other.max_amount or float('inf')) and other.min_amount <= upper:
                    raise ValidationError(self.env._(
                        "The tier from %(min)s overlaps another tier.", min=tier.min_amount))

    @api.depends('min_amount', 'max_amount', 'months')
    def _compute_display_name(self):
        for tier in self:
            upper = f"{tier.max_amount:,.2f}" if tier.max_amount else self.env._("above")
            tier.display_name = self.env._("%(min)s - %(max)s: %(months)s months",
                                           min=f"{tier.min_amount:,.2f}", max=upper, months=tier.months)

    @api.model
    def _get_tier(self, amount, company=None):
        """Tier covering an amount; tiers of the company win over the shared ones."""
        company = company or self.env.company
        tiers = self.sudo().search([('company_id', 'in', (company.id, False))], order='company_id, min_amount desc')
        for scoped in (tiers.filtered(lambda t: t.company_id == company), tiers.filtered(lambda t: not t.company_id)):
            for tier in scoped:
                if amount >= tier.min_amount and (not tier.max_amount or amount <= tier.max_amount):
                    return tier
            if scoped:
                break
        return self.browse()
