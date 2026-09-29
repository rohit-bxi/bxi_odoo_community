from odoo import api, fields, models
from odoo.exceptions import ValidationError


class TravelRequest(models.Model):
    _inherit = 'travel.request'

    training_request_id = fields.Many2one(
        'bxi.training.request', string='Specialized Training', tracking=True, index='btree_not_null',
        domain="[('employee_id', '=', employee_id), ('state', 'not in', ('draft', 'settled', 'refused', 'cancelled'))]",
        help="Travel to and from a specialized training is part of its consolidated cost.",
    )

    @api.constrains('training_request_id', 'employee_id')
    def _check_training_employee(self):
        for rec in self:
            if rec.training_request_id and rec.training_request_id.sudo().employee_id != rec.employee_id:
                raise ValidationError(self.env._("The training must be the traveller's own training."))
