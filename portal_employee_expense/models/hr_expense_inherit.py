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
        selection=[
            ('draft', 'Draft'),
            ('hr_approval', 'Hr Approval'),
            ('finance_approval', 'Finance Approval'),
            ('approved', 'Approved'),
            ('posted', 'Posted'),
            ('in_payment', 'In Payment'),
            ('paid', 'Paid'),
            ('refused', 'Refused'),
        ],
        string="Status",
        store=True, readonly=True,
        index=True,
        copy=False,
        default='draft',
        tracking=True,
    )  

    @api.model
    def create(self, vals_list):
        records = super().create(vals_list)

        for rec in records:
            rec.state = 'hr_approval'

        return records

    def action_hr_approve(self):
        for rec in self:
            if rec.state != 'hr_approval':
                raise UserError("Expense must be in HR Approval state.")
            rec.state = 'finance_approval'

    def action_finance_approved(self):
        for rec in self:
            if rec.state != 'finance_approval':
                raise UserError("Expense must be in Finance Approval state.")
            rec.state = 'approved'

    def action_refuse(self):
        for rec in self:
            rec.state = 'refused'

    def write(self, vals):
        res = super().write(vals)
        if 'state' in vals:
            for record in self:
                record._send_state_email()
        return res
    
    def _send_state_email(self):
        self.ensure_one()
        template = False
        email_to = False
        if self.state == 'hr_approval':
            template = self.env.ref('portal_employee_expense.email_template_hr')
            email_to = 'shekhawatritika2001@gmail.com'
        elif self.state == 'finance_approval':
            template = self.env.ref('portal_employee_expense.email_template_finance')
            email_to = 'shekhawatritika2001@gmail.com'
        if not template or not email_to:
            return
        template.send_mail(
            self.id,
            email_values={'email_to': email_to},
            force_send=True
        )

