from odoo import models, fields


class ESSLAttendanceSyncLog(models.Model):
    _name = 'essl.attendance.sync.log'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Biometric Attendance Synchronization Log'
    _rec_name = 'request_data'

    request_data = fields.Date(string='Record Date', tracking=True)
    response_data = fields.Text(string='Response', tracking=True)
    status = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
        ('exception', 'Exception')
    ], default='draft', string='Status', tracking=True)
    exception_reason = fields.Text(string='Exception Reason', tracking=True)
    company_id = fields.Many2one('res.company')
    device_id = fields.Many2one('essl.api.config', string='Device')
    work_location_id = fields.Many2one('hr.work.location', string='Location',
                                       help="Location of the device when the download ran.")
