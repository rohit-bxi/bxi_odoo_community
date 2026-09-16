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

    def action_submit(self):
        """
        Override: skip the HR approval step entirely.
        On submit, move expense directly to Finance Approval (submitted state)
        and send finance notification email.
        """
        # Call super to set approval_state = 'submitted' via the standard flow
        # but we override to auto-submit without needing HR approval
        for rec in self:
            if not rec.product_id:
                raise UserError("You cannot submit an expense without a category.")

        # Set approval_state to 'submitted' directly, bypassing manager checks
        self.sudo().write({'approval_state': 'submitted'})
        self.sudo().update_activities_and_mails()

        # Send finance approval notification
        for rec in self:
            rec._send_state_email()

    def action_finance_approved(self):
        """
        Finance team approves the expense — calls the standard action_approve flow.
        """
        self.action_approve()

    def _send_state_email(self):
        for rec in self:
            template = False
            if rec.state == 'submitted':
                template = self.env.ref(
                    'portal_employee_expense.email_template_finance',
                    raise_if_not_found=False
                )
            elif rec.state == 'approved':
                template = self.env.ref(
                    'portal_employee_expense.email_template_expense_approved',
                    raise_if_not_found=False
                )
            elif rec.state == 'refused':
                template = self.env.ref(
                    'portal_employee_expense.email_template_expense_refused',
                    raise_if_not_found=False
                )

            if template:
                template.send_mail(rec.id, force_send=True)

    def write(self, vals):
        old_states = {rec.id: rec.state for rec in self}
        res = super().write(vals)
        if 'approval_state' in vals or 'state' in vals:
            for record in self:
                if old_states.get(record.id) != record.state:
                    record._send_state_email()
        return res
