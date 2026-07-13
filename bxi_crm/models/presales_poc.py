from odoo import fields, models, api, _


class PresalesPOC(models.Model):
    _name = "presales.poc"
    _description = "Presales POC"
    _rec_name = "name"

    name = fields.Char(
        string="Name",
        required=True,
    )

    employee_id = fields.Many2one('hr.employee',
        string="Employee",
    )


    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            self.name = self.employee_id.name

