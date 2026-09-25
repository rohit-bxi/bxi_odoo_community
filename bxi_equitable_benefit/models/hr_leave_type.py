from odoo import fields, models


class HrLeaveType(models.Model):
    _inherit = 'hr.leave.type'

    eb_is_unpaid = fields.Boolean(
        string='Unpaid (Equitable Benefit)',
        help="Days of this type reduce the Equitable Benefit pro-rata once they exceed the configured threshold.")
    eb_is_unauthorized = fields.Boolean(
        string='Unauthorized Absence (Equitable Benefit)',
        help="Days of this type count as unauthorized absence for Equitable Benefit eligibility.")
