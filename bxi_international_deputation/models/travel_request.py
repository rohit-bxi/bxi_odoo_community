from odoo import fields, models


class TravelRequest(models.Model):
    _inherit = 'travel.request'

    deputation_ids = fields.One2many('bxi.deputation', 'travel_request_id', string='Deputations')

    def action_create_deputation(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('International Deputation'),
            'res_model': 'bxi.deputation',
            'view_mode': 'form',
            'context': {
                'default_employee_id': self.employee_id.id,
                'default_travel_request_id': self.id,
                'default_host_country_id': self.to_country.id,
                'default_planned_start_date': self.departure_date,
                'default_planned_end_date': self.return_date,
            },
        }
