from odoo import models

PARAM_PREFIX = 'bxi_gift_entertainment.'


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def _gift_band_rank(self):
        """Position of the employee's role band in the configured band order, -1 when unknown."""
        self.ensure_one()
        order = self.env['ir.config_parameter'].sudo().get_param(PARAM_PREFIX + 'band_order', '')
        bands = [band.strip().upper() for band in order.split(',') if band.strip()]
        band = (self.sudo().role_band or '').strip().upper()
        return bands.index(band) if band in bands else -1

    def _gift_skip_level_manager(self):
        """Reporting manager's reporting manager, climbing up until the minimum band is reached."""
        self.ensure_one()
        params = self.env['ir.config_parameter'].sudo()
        minimum = params.get_param(PARAM_PREFIX + 'min_skip_manager_band', 'E3').strip().upper()
        order = [b.strip().upper() for b in params.get_param(PARAM_PREFIX + 'band_order', '').split(',')]
        min_rank = order.index(minimum) if minimum in order else -1
        manager = self.sudo().parent_id.parent_id
        seen = self.env['hr.employee']
        while manager and manager not in seen:
            if manager._gift_band_rank() >= min_rank:
                return manager
            seen |= manager
            manager = manager.parent_id
        return self.env['hr.employee']

    def _gift_is_l1_or_above(self):
        """Whether the employee is an L1 Head of someone, or MD / CEO / CFO / Board."""
        self.ensure_one()
        user = self.sudo().user_id
        if user and any(user.has_group('bxi_gift_entertainment.group_gift_%s' % role)
                        for role in ('md', 'ceo', 'cfo', 'board')):
            return True
        return bool(self.sudo().search_count([('l1_head_id', '=', self.id)], limit=1))
