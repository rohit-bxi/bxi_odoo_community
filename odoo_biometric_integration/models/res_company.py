from odoo import models, fields, api


class ResCompanyInherit(models.Model):
    _inherit = 'res.company'

    device_id = fields.Many2one('essl.api.config')