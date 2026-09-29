from odoo import api, fields, models

# Travel requests whose cost the company has approved.
APPROVED_TRAVEL_STATES = ('approve',)


class BxiTrainingRequest(models.Model):
    _inherit = 'bxi.training.request'

    travel_request_ids = fields.One2many('travel.request', 'training_request_id', string='Travel Requests')
    travel_cost = fields.Monetary(
        string='Travel (Travel Requests)', currency_field='currency_id', compute='_compute_costs', store=True,
        help="Cost of the approved travel requests linked to the training, paid by the company.",
    )

    @api.depends('travel_request_ids.total_submitted_expense', 'travel_request_ids.state')
    def _compute_costs(self):
        for rec in self:
            travels = rec.sudo().travel_request_ids.filtered(lambda t: t.state in APPROVED_TRAVEL_STATES)
            rec.travel_cost = sum(travels.mapped('total_submitted_expense'))
        return super()._compute_costs()

    def _get_extra_actual_cost(self):
        return super()._get_extra_actual_cost() + self.travel_cost

    def action_view_travel_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Travel Requests'),
            'res_model': 'travel.request',
            'view_mode': 'list,form',
            'domain': [('training_request_id', '=', self.id)],
            'context': {'default_training_request_id': self.id, 'default_employee_id': self.employee_id.id},
        }
