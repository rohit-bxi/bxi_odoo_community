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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('state') or vals.get('state') == 'draft':
                vals['state'] = 'finance_approval'

        records = super().create(vals_list)

        for rec in records:
            if rec.state == 'finance_approval':
                rec._send_state_email()

        return records

    # HR approval step removed; expenses go directly to finance approval on create

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

