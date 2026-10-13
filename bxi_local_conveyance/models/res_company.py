from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    conveyance_finance_user_id = fields.Many2one(
        'res.users', string='Local Conveyance Finance',
        help="Approves conveyance claims as Finance. Empty: any Local Conveyance Finance Officer.",
    )
    conveyance_hr_user_id = fields.Many2one(
        'res.users', string='Local Conveyance HR',
        help="Approves conveyance claims as HR. Empty: any Local Conveyance HR Officer.",
    )
