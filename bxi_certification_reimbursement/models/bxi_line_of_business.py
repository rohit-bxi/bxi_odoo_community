from odoo import models, fields


class BxiLineOfBusiness(models.Model):
    _name = 'bxi.line.of.business'
    _description = 'Line of Business'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code', required=True)
    academy_head_id = fields.Many2one(
        'hr.employee',
        string='Academy Head',
        help="Approves certifications that are not in the approved list "
             "and Udemy courses for Digital Business.",
    )
    academy_user_ids = fields.Many2many(
        'res.users',
        'bxi_lob_academy_user_rel',
        'lob_id',
        'user_id',
        string='Academy Team',
        help="Users who maintain the approved certification list for this LoB.",
    )
    is_digital_business = fields.Boolean(
        string='Digital Business',
        help="Udemy courses of this LoB need prior approval from the academy.",
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        'unique(code, company_id)',
        'The Line of Business code must be unique per company.',
    )
