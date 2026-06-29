from odoo import fields, models


class PresalesPOC(models.Model):
    _name = "presales.poc"
    _description = "Presales POC"
    _rec_name = "name"

    name = fields.Char(
        string="Name",
        required=True,
    )

    employee_id = fields.Many2one('hr.employee',
        string="Email",
    )