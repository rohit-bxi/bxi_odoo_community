from odoo import models
from odoo.exceptions import UserError

from odoo.addons.bxi_local_conveyance.models.product_template import TRAVEL_KINDS

# Travel requests that did not or will not take place.
_NO_TRAVEL_STATES = ('draft', 'cancel')


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    def _check_conveyance_policy(self):
        notes = super()._check_conveyance_policy()
        if self.conveyance_kind in TRAVEL_KINDS or self.conveyance_kind == 'parking_toll':
            travel = self.env['travel.request'].sudo().search([
                ('employee_id', '=', self.employee_id.id),
                ('state', 'not in', _NO_TRAVEL_STATES),
                ('departure_date', '<=', self.date),
            ]).filtered(lambda rec: self.date <= (rec.return_date or rec.departure_date))[:1]
            # Clause 7: residence to airport and back, on the days the travel starts and ends.
            to_airport = self.conveyance_purpose == 'airport' and self.date in (
                travel.departure_date, travel.return_date)
            if travel and not to_airport:
                raise UserError(self.env._(
                    "%(claim)s: you were travelling from %(origin)s to %(destination)s on %(date)s (travel request "
                    "%(travel)s). Intercity travel expenses are processed through HR and Finance with the travel "
                    "request, not as local conveyance.",
                    claim=self.name, origin=travel.from_city, destination=travel.to_city, date=self.date,
                    travel=travel.display_name))
        return notes
