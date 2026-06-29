from odoo import models, fields

class ResUsers(models.Model):
    _inherit = 'res.users'

    signature_name = fields.Char(string="Signature Name")