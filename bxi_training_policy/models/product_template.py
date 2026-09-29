from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_training_expense = fields.Boolean(
        string='Specialized Training Expense',
        help="Claimed only from a specialized training, never as a regular expense.",
    )
