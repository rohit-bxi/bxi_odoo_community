from odoo import fields, models


class HrVersion(models.Model):
    _inherit = 'hr.version'

    eb_annual_component_a = fields.Monetary(
        string='Annualized Component A', groups='hr.group_hr_user', tracking=True,
        help="Yearly value of Component A as defined in the offer letter. "
             "Equitable Benefit is calculated as a percentage of this amount.")

    def write(self, vals):
        res = super().write(vals)
        if vals.get('departure_date'):
            # Separations without a resignation (termination, absconding, ...) are settled too.
            for version in self.filtered('departure_date'):
                version.employee_id._eb_settle_separation(version.departure_date)
        return res
