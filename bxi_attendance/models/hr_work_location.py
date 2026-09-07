# -*- coding: utf-8 -*-
from odoo import models, fields


class HrWorkLocation(models.Model):
    _inherit = 'hr.work.location'

    office = fields.Boolean(string='Office Location', default=False)
    home = fields.Boolean(string='Home Location', default=False)
    latitude = fields.Float(string='Latitude', digits=(16, 8))
    longitude = fields.Float(string='Longitude', digits=(16, 8))
    radius_km = fields.Float(string='Allowed Radius (km)', default=2.5)
    company_id = fields.Many2one('res.company', string='Company')
    # Weekly enforcement: require employees assigned to this location to
    # work from office a minimum number of days per week.
    enforce_weekly_requirement = fields.Boolean(
        string='Enforce Weekly Onsite Requirement',
        default=False,
        help='If set, employees for whom this location applies must work from this location for a minimum number of days per week.'
    )
    required_days_per_week = fields.Integer(
        string='Required Onsite Days / Week',
        default=3,
        help='Minimum number of days per calendar week the employee must work from this location when enforcement is active.'
    )
