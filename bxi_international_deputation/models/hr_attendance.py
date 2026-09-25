from odoo import models


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    def _validate_location_access(self, vals=None):
        """Employees on a host country payroll work abroad: the home office geofence does not apply."""
        employee_id = (vals or {}).get('employee_id')
        if employee_id:
            employee = self.env['hr.employee'].sudo().browse(employee_id).exists()
            if employee.is_on_deputation:
                return
        return super()._validate_location_access(vals)
