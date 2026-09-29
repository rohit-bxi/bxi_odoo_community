from odoo import models
from odoo.exceptions import UserError

from odoo.addons.bxi_local_conveyance.models.product_template import TRAVEL_KINDS

# Trainings that did not or will not take place.
_NO_TRAINING_STATES = ('draft', 'refused', 'cancelled')


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    def _check_conveyance_policy(self):
        notes = super()._check_conveyance_policy()
        if self.conveyance_kind in TRAVEL_KINDS or self.conveyance_kind == 'parking_toll':
            training = self.env['bxi.training.request'].sudo().search([
                ('employee_id', '=', self.employee_id.id),
                ('state', 'not in', _NO_TRAINING_STATES),
                ('start_date', '<=', self.date),
            ]).filtered(lambda rec: self.date <= (rec.actual_end_date or rec.end_date))[:1]
            if training:
                raise UserError(self.env._(
                    "%(claim)s: you were attending the training %(training)s on %(date)s. Local travel related to "
                    "training programs is not reimbursed; training travel is claimed with the training.",
                    claim=self.name, training=training.training_name, date=self.date))
        return notes
