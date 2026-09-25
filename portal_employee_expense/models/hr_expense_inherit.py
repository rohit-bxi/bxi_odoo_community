from odoo import models, fields, api
from datetime import date as py_date
from odoo.exceptions import UserError


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    reimbursement_date = fields.Date(
        string="Reimbursement Date",
        compute="_compute_reimbursement_date",
        store=True
    )

    @api.depends('date')
    def _compute_reimbursement_date(self):
        for rec in self:
            if rec.date:
                expense_date = rec.date

                # Calculate next month
                if expense_date.month == 12:
                    next_month = 1
                    year = expense_date.year + 1
                else:
                    next_month = expense_date.month + 1
                    year = expense_date.year

                # Set to 15th of next month
                rec.reimbursement_date = py_date(year, next_month, 15)
            else:
                rec.reimbursement_date = False

    state = fields.Selection(
        selection_add=[
            ('finance_approval', 'Finance Approval'),
        ],
        ondelete={'finance_approval': 'set default'},
        string="Status",
        compute=None,
        store=True, readonly=True,
        index=True,
        copy=False,
        default='draft',
        tracking=True,
    )

    @api.depends('account_move_id.payment_state', 'account_move_id.state', 'approval_state')
    def _compute_state(self):
        for expense in self:
            if not expense.account_move_id and expense.state in ('finance_approval', 'approved', 'refused'):
                continue
            super(HrExpense, expense)._compute_state()

    @api.model
    def _portal_expense_product_domain(self):
        """Expense categories employees can pick on the portal."""
        return [('can_be_expensed', '=', True)]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec, vals in zip(records, vals_list):
            if vals.get('state') == 'finance_approval':
                rec.state = 'finance_approval'
                rec._send_state_email()

        return records

    # HR approval step removed; expenses go directly to finance approval on create


    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError("Only draft expenses can be submitted.")
            if not rec.product_id:
                raise UserError("You cannot submit an expense without a category.")
            rec.write({'state': 'finance_approval'})

    def action_hr_approve(self):
        print("pass")

    def action_finance_approved(self):
        for rec in self:
            if rec.state != 'finance_approval':
                raise UserError("Expense must be in Finance Approval state.")
            rec.state = 'approved'

    def action_refuse(self):
        for rec in self:
            rec.state = 'refused'

    def write(self, vals):
        old_states = {rec.id: rec.state for rec in self}
        res = super().write(vals)
        if 'state' in vals:
            for record in self:
                if old_states.get(record.id) != record.state:
                    record._send_state_email()
        return res

    def _send_state_email(self):
        for rec in self:
            template = False
            if rec.state == 'finance_approval':
                template = self.env.ref('portal_employee_expense.email_template_finance', raise_if_not_found=False)
            elif rec.state == 'approved':
                template = self.env.ref('portal_employee_expense.email_template_expense_approved', raise_if_not_found=False)
            elif rec.state == 'refused':
                template = self.env.ref('portal_employee_expense.email_template_expense_refused', raise_if_not_found=False)

            if template:
                template.send_mail(rec.id, force_send=True)

