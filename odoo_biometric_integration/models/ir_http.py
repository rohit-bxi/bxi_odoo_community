from odoo import api, models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @api.model
    def lazy_session_info(self):
        # hr_attendance fills this from HrAttendance._get_user_attendance_data directly,
        # so the controller override in this module does not apply to it.
        res = super().lazy_session_info()
        if res.get('attendance_user_data'):
            res['attendance_user_data']['manual_attendance_allowed'] = \
                self.env.user.employee_id.essl_manual_attendance_allowed
        return res
