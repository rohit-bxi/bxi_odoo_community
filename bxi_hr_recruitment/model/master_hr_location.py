from odoo import models, fields



class HrLocation(models.Model):
    _name = 'hr.location'
    _description = 'Job Location Master'

    name = fields.Char(string="Location", required=True)
    active = fields.Boolean(default=True)
