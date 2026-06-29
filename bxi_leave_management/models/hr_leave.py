from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date


class HrEmployeeLeave(models.Model):
    _inherit = 'hr.leave'

    @api.constrains('holiday_status_id', 'request_date_from', 'request_date_to')
    def _check_rh_leave_rules(self):
        for rec in self:

            # Apply only for RH
            if not rec.holiday_status_id or rec.holiday_status_id.time_off_code != 'RH':
                continue

            # =========================
            # RULE 1: ONLY 1 DAY
            # =========================
            if rec.request_date_from != rec.request_date_to:
                raise ValidationError("RH leave can only be applied for 1 day.")

            # =========================
            # RULE 2: ONLY OPTIONAL HOLIDAY DATE
            # =========================
            optional_holiday = self.env['l10n.in.hr.leave.optional.holiday'].search([
                ('date', '=', rec.request_date_from),
                ('company_id', '=', rec.company_id.id)
            ], limit=1)

            if not optional_holiday:
                raise ValidationError(
                    "RH leave can only be applied on Optional Holiday dates."
                )