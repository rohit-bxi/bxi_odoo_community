from odoo import models, fields, api, _

class HelpdeskCategory(models.Model):
    _name = 'helpdesk.category'
    _description = 'Helpdesk Category'

    name = fields.Char(required=True)
    team_id = fields.Many2one(
        'helpdesk.team',
        string='Helpdesk Team',
        required=True,
        ondelete='cascade'
    )
    active = fields.Boolean(default=True)
