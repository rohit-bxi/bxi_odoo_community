# -*- coding: utf-8 -*-
from odoo import models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def _attendance_action_change(self, geo_information=None):
        """Close a forgotten attendance from a previous day before the
        check-in/check-out toggle, so the button checks the employee in
        instead of closing yesterday's attendance with today's time."""
        self.ensure_one()
        if self.attendance_state == 'checked_in':
            stale = self.env['hr.attendance']._get_stale_open_attendances(self)
            if stale:
                stale._close_missed_checkout()
                self.invalidate_recordset(['last_attendance_id', 'attendance_state'])
        return super()._attendance_action_change(geo_information)
