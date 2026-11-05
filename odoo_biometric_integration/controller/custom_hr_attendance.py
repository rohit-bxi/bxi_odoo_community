from odoo import http, _
from odoo.exceptions import UserError
from odoo.http import request
from odoo.addons.hr_attendance.controllers.main import HrAttendance


class CustomHrAttendance(HrAttendance):

    @staticmethod
    def _get_user_attendance_data(employee):
        response = super(CustomHrAttendance, CustomHrAttendance)._get_user_attendance_data(employee)
        if employee:
            response.update({
                'manual_attendance_allowed': employee.essl_manual_attendance_allowed
            })
        return response

    @staticmethod
    def _get_employee_info_response(employee):
        # Returned after a systray check in/out; the parent builds it from
        # HrAttendance._get_user_attendance_data directly, bypassing the override above.
        response = super(CustomHrAttendance, CustomHrAttendance)._get_employee_info_response(employee)
        if employee:
            # read before the check in/out of this same request; it may have changed
            employee.invalidate_recordset(['essl_manual_attendance_allowed'])
            response.update({
                'manual_attendance_allowed': employee.essl_manual_attendance_allowed
            })
        return response

    @http.route()
    def systray_attendance(self, latitude=False, longitude=False):
        # The systray button is hidden for these employees; also refuse direct calls.
        employee = request.env.user.with_company(self._get_active_company(request)).employee_id
        if employee and not employee.essl_manual_attendance_allowed:
            raise UserError(_("Your attendance is recorded by the biometric device at your work "
                              "location. Manual check in/out is only available on days covered "
                              "by an approved exception request."))
        return super().systray_attendance(latitude=latitude, longitude=longitude)
