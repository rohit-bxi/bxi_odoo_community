from odoo import fields, models


class HrDepartment(models.Model):
    _inherit = 'hr.department'

    is_sales_team = fields.Boolean(
        string='Sales Team',
        help="Employees of this department and its sub-departments can claim food under the Food Policy.",
    )
