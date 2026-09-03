from odoo import models, fields


class BxiShiftEmployeeLocation(models.Model):
    _name = "bxi.shift.employee.location"
    _description = "Per-day Employee Work Location Override"

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, ondelete='cascade')
    date = fields.Date(string='Date', required=True)
    location_id = fields.Many2one('hr.work.location', string='Work Location')
    exception_id = fields.Many2one('bxi.shift.exception', string='Source Exception', ondelete='cascade')

    _sql_constraints = [
        ('employee_date_unique', 'unique(employee_id, date)', 'An override for this employee and date already exists.'),
    ]
