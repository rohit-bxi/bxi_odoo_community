from odoo import models


class BxiEbPayout(models.Model):
    _inherit = 'bxi.eb.payout'

    def _eb_schedules(self, date_from, date_to):
        """Approved shift requests set the schedule of their days. Applying one overwrites the schedule of the
        contract until it ends, so the days before a shift still applied had its original schedule."""
        schedules = super()._eb_schedules(date_from, date_to)
        requests = self.env['bxi.shift.request'].sudo().search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'approved'),
            ('date_from', '<=', date_to),
            '|', ('date_to', '=', False), ('date_to', '>=', date_from),
        ], order='date_from, id')
        for request in requests.filtered(lambda req: req.schedule_applied and not req.schedule_reverted
                                         and req.original_shift_id):
            for day, schedule in schedules.items():
                if day < request.date_from and schedule == request.requested_shift_id:
                    schedules[day] = request.original_shift_id
        for request in requests:
            for day in schedules:
                if request.date_from <= day and (not request.date_to or day <= request.date_to):
                    schedules[day] = request.requested_shift_id
        return schedules
