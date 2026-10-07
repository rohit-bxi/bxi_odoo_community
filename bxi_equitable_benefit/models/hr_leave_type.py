from odoo import api, fields, models


class HrLeaveType(models.Model):
    _inherit = 'hr.leave.type'

    eb_is_unpaid = fields.Boolean(
        string='Unpaid (Equitable Benefit)',
        help="Days of this type reduce the Equitable Benefit pro-rata once they exceed the configured threshold.")
    eb_is_unauthorized = fields.Boolean(
        string='Unauthorized Absence (Equitable Benefit)',
        help="Days of this type count as unauthorized absence for Equitable Benefit eligibility.")

    @api.model
    def _eb_flag_default_unpaid_types(self):
        """Flag the existing unpaid leave types (LWP / Leave Without Pay) unless some type is flagged already."""
        if self.with_context(active_test=False).search_count([('eb_is_unpaid', '=', True)], limit=1):
            return
        domain = ['|', '|', ('name', 'ilike', 'without pay'), ('name', 'ilike', 'loss of pay'),
                  ('name', 'ilike', 'unpaid')]
        if 'time_off_code' in self._fields:
            domain = ['|', ('time_off_code', 'in', ('LWP', 'LOP'))] + domain
        self.with_context(active_test=False).search(domain).write({'eb_is_unpaid': True})
