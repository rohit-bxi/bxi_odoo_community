# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    is_auto_checkout = fields.Boolean(string='Auto Check-out', default=False)

    @api.model
    def _cron_auto_checkout(self):
        """
        Scheduled action to auto check-out all attendance records where check-out is missing.
        Runs daily at 11:50 PM and sets check_out to current time with is_auto_checkout=True.
        """
        open_attendances = self.search([('check_out', '=', False)])
        if open_attendances:
            now = fields.Datetime.now()
            open_attendances.write({
                'check_out': now,
                'is_auto_checkout': True,
            })
