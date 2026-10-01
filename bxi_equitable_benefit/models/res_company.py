from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    eb_suspended_from = fields.Date(
        string='Equitable Benefit Suspended From',
        help="The benefit stops accruing from this date and no new work pattern can start on or after it. "
             "Leave empty while the policy applies.")
