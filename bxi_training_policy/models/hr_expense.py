from odoo import api, fields, models
from odoo.exceptions import UserError

# Amount-related fields that cannot change once a training claim is submitted.
_LOCKED_FIELDS = {
    'total_amount', 'total_amount_currency', 'price_unit', 'quantity', 'product_id',
    'employee_id', 'currency_id', 'training_request_id', 'analytic_distribution',
}


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    training_request_id = fields.Many2one(
        'bxi.training.request', string='Training', index='btree_not_null', ondelete='set null', copy=False)
    is_training_expense = fields.Boolean(related='product_id.is_training_expense')
    state = fields.Selection(
        selection_add=[
            ('training_approval', 'Training Claim Approval'),
            ('finance_approval',),
        ],
        ondelete={'training_approval': 'set default'},
    )

    @api.model
    def _portal_expense_product_domain(self):
        # Training costs are claimed through the training only.
        return super()._portal_expense_product_domain() + [('is_training_expense', '=', False)]

    def action_submit(self):
        if any(expense.is_training_expense for expense in self):
            raise UserError(self.env._(
                "Specialized Training costs are claimed from the training (Employees > Specialized Training, or "
                "My Trainings on the portal)."))
        return super().action_submit()

    def action_finance_approved(self):
        for expense in self.filtered('training_request_id'):
            if expense.training_request_id.state != 'finance_approval':
                raise UserError(self.env._(
                    "%(line)s: the training claim has not been approved by the Reporting Manager, HR and Employee "
                    "Services yet.", line=expense.name))
        return super().action_finance_approved()

    @api.model_create_multi
    def create(self, vals_list):
        expenses = super().create(vals_list)
        if not self.env.su:
            for expense in expenses.filtered('training_request_id'):
                request = expense.training_request_id
                if request.state != 'completed':
                    raise UserError(self.env._("Claim lines are added once the training is completed."))
                if not expense.product_id.is_training_expense:
                    raise UserError(self.env._(
                        "Training costs are claimed under the \"Specialized Training\" categories only."))
        return expenses

    def write(self, vals):
        if not self.env.su and self.filtered('training_request_id') and (_LOCKED_FIELDS & vals.keys()):
            locked = self.filtered(lambda exp: exp.training_request_id and exp.state != 'draft')
            if locked:
                raise UserError(self.env._("Submitted training claim lines cannot be modified."))
        res = super().write(vals)
        if 'state' in vals:
            self.training_request_id._sync_from_expenses()
        return res


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        requests = posted.sudo().expense_ids.training_request_id.filtered(lambda r: r.state == 'settled')
        for request in requests:
            request._reconcile_settlement()
        return posted
