from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_certification_expense = fields.Boolean(
        string='Certification Expense',
        help="Reimbursable certification cost (exam fee, DD charges, courier). "
             "Claimed only through a certification request.",
    )
