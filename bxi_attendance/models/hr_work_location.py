# -*- coding: utf-8 -*-
from odoo import models, fields


class HrWorkLocation(models.Model):
    _inherit = 'hr.work.location'

    latitude = fields.Float(string='Latitude', digits=(16, 8))
    longitude = fields.Float(string='Longitude', digits=(16, 8))
    radius_km = fields.Float(string='Allowed Radius (km)', default=2.5)
    company_id = fields.Many2one('res.company', string='Company')
    resource_calendar_id = fields.Many2one('resource.calendar', string='Working Schedule')
