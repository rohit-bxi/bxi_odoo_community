from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    conveyance_hr_user_id = fields.Many2one(
        'res.users', string='Local Conveyance HR',
        help="Approves conveyance claims as HR. Empty: any Local Conveyance HR Officer.",
    )
