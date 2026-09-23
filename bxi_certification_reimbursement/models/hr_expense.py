from odoo import models, fields, api
from odoo.exceptions import UserError

# Amount-related fields that cannot change once a certification claim is submitted.
_LOCKED_FIELDS = {
    'total_amount', 'total_amount_currency', 'price_unit', 'quantity', 'product_id',
    'employee_id', 'currency_id', 'certification_request_id', 'analytic_distribution',
}


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    certification_request_id = fields.Many2one(
        'bxi.certification.request',
        string='Certification Request',
        index='btree_not_null',
        ondelete='set null',
        copy=False,
    )
    is_certification_expense = fields.Boolean(related='product_id.is_certification_expense')
    state = fields.Selection(
        selection_add=[
            ('cert_approval', 'Certification Approval'),
            ('finance_approval',),
        ],
        ondelete={'cert_approval': 'set default'},
    )

    @api.model
    def _portal_expense_product_domain(self):
        # Certification costs are claimed through the certification request only.
        return super()._portal_expense_product_domain() + [('is_certification_expense', '=', False)]

    def action_submit(self):
        if any(expense.is_certification_expense for expense in self):
            raise UserError(self.env._(
                "Certification expenses are claimed from the certification request "
                "(Employees > Certifications > My Requests)."
            ))
        return super().action_submit()

    def action_finance_approved(self):
        for expense in self.filtered('certification_request_id'):
            if expense.certification_request_id.state != 'finance_approval':
                raise UserError(self.env._(
                    "%(line)s: the certification claim is not ready for Finance approval "
                    "(approvals or service agreement pending).",
                    line=expense.name,
                ))
        return super().action_finance_approved()

    def write(self, vals):
        if not self.env.su and self.filtered('certification_request_id') and (_LOCKED_FIELDS & vals.keys()):
            locked = self.filtered(lambda exp: exp.certification_request_id and exp.state != 'draft')
            if locked:
                raise UserError(self.env._("Submitted certification claim lines cannot be modified."))
        res = super().write(vals)
        if 'state' in vals:
            self.certification_request_id._sync_from_expenses()
        return res
