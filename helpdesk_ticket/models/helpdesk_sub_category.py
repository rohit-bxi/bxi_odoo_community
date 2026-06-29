from odoo import models, fields, api, _

class HelpdeskSubCategory(models.Model):
    _name = 'helpdesk.sub.category'
    _description = 'Helpdesk Sub Category'

    name = fields.Char(required=True)
    category_id = fields.Many2one(
        'helpdesk.category',
        string='Category',
        domain="[('team_id', '=', team_id)]",
        required=True,
        ondelete='cascade'
    )
    team_id = fields.Many2one(
        'helpdesk.team',
        string='Helpdesk Team'
    )
    active = fields.Boolean(default=True)
