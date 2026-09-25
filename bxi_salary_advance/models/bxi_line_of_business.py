from odoo import fields, models


class BxiLineOfBusiness(models.Model):
    _inherit = 'bxi.line.of.business'

    hr_head_id = fields.Many2one(
        'hr.employee',
        string='LoB HR Head (India)',
        help="Approves exceptions to the Salary Advance Policy for offshore employees of this LoB.",
    )
