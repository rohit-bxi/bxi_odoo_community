from odoo import models, fields

# in_mode of attendances the employee checked in to themselves
EMPLOYEE_CHECKIN_MODES = ('systray', 'kiosk')


class HrAttendanceInherit(models.Model):
    _inherit = 'hr.attendance'

    essl_punch_history_ids = fields.One2many('essl.punch.history', 'essl_attendance_id')
    synced_with_essl = fields.Boolean()
    essl_status = fields.Char(string="Biometric Status")


class ESSLPunchHistory(models.Model):
    _name = 'essl.punch.history'
    _description = 'Biometric Punch History'
    _order = 'punch_in_times'

    essl_attendance_id = fields.Many2one('hr.attendance', ondelete='cascade', index=True)
    punch_in_times = fields.Datetime(string="Punch Time")
