from odoo import api, fields, models
from odoo.exceptions import ValidationError


class BxiConveyanceTravelPlan(models.Model):
    """The mode of local travel an employee is entitled to by band (policy table TP1, TP2, TP3)."""
    _name = 'bxi.conveyance.travel.plan'
    _description = 'Local Conveyance Travel Plan'
    _order = 'sequence, band_min desc, id'

    name = fields.Char(string='Travel Plan', required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    band_min = fields.Integer(string='From Band', required=True, help="Lowest band (E-grade) of the plan.")
    band_max = fields.Integer(
        string='To Band', help="Highest band (E-grade) of the plan. 0 means no upper limit.")
    allow_taxi = fields.Boolean(string='Taxi', default=True)
    allow_auto = fields.Boolean(
        string='Auto-Rickshaw',
        help="Auto-rickshaw claims outside emergencies. In an emergency any employee may claim an auto.")
    taxi_needs_reason = fields.Boolean(
        string='Taxi Only Where No Auto',
        help="A taxi is claimed only where no auto-rickshaw is available: the employee states why.")
    description = fields.Char(string='Bands and Mode of Travel', translate=True)

    @api.constrains('band_min', 'band_max', 'active')
    def _check_bands(self):
        for plan in self:
            if plan.band_min < 0 or plan.band_max < 0:
                raise ValidationError(self.env._("Bands cannot be negative."))
            if plan.band_max and plan.band_max < plan.band_min:
                raise ValidationError(self.env._(
                    "%(plan)s: the highest band is lower than the lowest band.", plan=plan.name))
        plans = self.search([])
        for plan in plans:
            for other in plans - plan:
                if plan._overlaps(other):
                    raise ValidationError(self.env._(
                        "The bands of %(plan)s and %(other)s overlap.", plan=plan.name, other=other.name))

    def _overlaps(self, other):
        self.ensure_one()
        high = self.band_max or float('inf')
        other_high = other.band_max or float('inf')
        return self.band_min <= other_high and other.band_min <= high

    @api.model
    def _get_for_band(self, band_level):
        """The plan covering the given band, or an empty recordset."""
        for plan in self.search([]):
            if plan.band_min <= band_level and (not plan.band_max or band_level <= plan.band_max):
                return plan
        return self.browse()
