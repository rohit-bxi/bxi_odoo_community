from odoo import models, fields, api
from odoo.exceptions import ValidationError


class HrLeaveType(models.Model):
    _inherit = 'hr.leave.type'

    time_off_code = fields.Char(
        string="Time Off Code",
        help="Unique code for Time Off Type"
    )

    _sql_constraints = [
        ('time_off_code_unique', 'unique(time_off_code)', 'Time Off Code must be unique!')
    ]

    @api.onchange('time_off_code')
    def _onchange_time_off_code(self):
        if self.time_off_code:
            self.time_off_code = self.time_off_code.upper()


    @api.onchange('duration_display')
    def _onchange_rh_rules(self):
        for rec in self:

            if not rec.holiday_status_id or rec.holiday_status_id.time_off_code != 'RH':
                return

            # =========================
            # RULE 1: MAX 1 DAY
            # =========================
            if rec.duration_display and rec.duration_display > 1:
                rec.duration_display = 1
                return {
                    'warning': {
                        'title': "Invalid RH Leave",
                        'message': "RH leave can only be applied for 1 day."
                    }
                }

            # =========================
            # RULE 2: VALID OPTIONAL HOLIDAY DATE
            # =========================
            leave_date = rec.request_date_from

            if leave_date:
                optional_holiday = self.env['optional.holiday'].search([
                    ('date', '=', leave_date),
                    ('company_id', '=', rec.company_id.id)
                ], limit=1)

                if not optional_holiday:
                    rec.request_date_from = False
                    rec.request_date_to = False

                    return {
                        'warning': {
                            'title': "Invalid Date",
                            'message': "RH can only be applied on Optional Holiday dates."
                        }
                    }