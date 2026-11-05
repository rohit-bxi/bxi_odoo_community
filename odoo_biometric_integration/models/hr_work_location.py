from odoo import models, fields


class HrWorkLocation(models.Model):
    _inherit = 'hr.work.location'

    essl_biometric_only = fields.Boolean(
        string="Biometric Attendance Only",
        help="Employees whose usual work location for the day is this one, and who are linked to a "
             "biometric device (device and Biometric Employee Code set), cannot check in/out manually.")

    def _essl_flag_default_biometric_locations(self):
        """The Udaipur office records attendance on the biometric device."""
        self.with_context(active_test=False).search([('name', '=ilike', 'udaipur')]).essl_biometric_only = True
