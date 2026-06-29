from odoo import models, fields,api

class ResUsers(models.Model):
    _inherit = 'res.users'

    vender_custmer_access = fields.Boolean(
        string="Is Vendor/Is Customer Access"
    )
