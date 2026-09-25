from odoo import fields, models


class HrVersion(models.Model):
    _inherit = 'hr.version'

    eb_annual_component_a = fields.Monetary(
        string='Annualized Component A', groups='hr.group_hr_user', tracking=True,
        help="Yearly value of Component A as defined in the offer letter. "
             "Equitable Benefit is calculated as a percentage of this amount.")
