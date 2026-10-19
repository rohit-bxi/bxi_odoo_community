from odoo import models, fields, api
from datetime import date as py_date
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


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
            ('hr_approval', 'Hr Approval'),
            ('finance_approval', 'Finance Approval'),
        ],
        ondelete={'hr_approval': 'set default', 'finance_approval': 'set default'},
        compute='_compute_state',
        store=True,
        readonly=False,
    )

    @api.depends('account_move_id', 'account_move_id.state', 'account_move_id.payment_state', 'approval_state', 'amount_residual')
    def _compute_state(self):
        records_to_super = self.filtered(
            lambda exp: exp.account_move_id or exp.state not in ('draft', 'hr_approval', 'finance_approval', 'approved', 'refused')
        )
        if records_to_super:
            super(HrExpense, records_to_super)._compute_state()
        for expense in (self - records_to_super):
            expense.state = expense.state or expense.approval_state or 'draft'

    @api.model
    def _portal_expense_product_domain(self):
        """Expense categories employees can pick on the portal."""
        return [('can_be_expensed', '=', True)]

    @api.model_create_multi
    def create(self, vals_list):
        clean_vals_list = []
        target_states = []
        for vals in vals_list:
            v = dict(vals)
            amt = v.get('total_amount_currency') or v.get('total_amount') or 0.0
            if amt:
                v['total_amount_currency'] = amt
                v['total_amount'] = amt
                if not v.get('price_unit'):
                    qty = v.get('quantity') or 1.0
                    v['price_unit'] = amt / qty

            target_state = v.pop('state', None)
            target_states.append(target_state)
            clean_vals_list.append(v)

        records = super().create(clean_vals_list)

        for rec, target_state in zip(records, target_states):
            if target_state and target_state != 'draft':
                rec.write({'state': target_state})

        return records

    # HR approval step removed; expenses go directly to finance approval on create


    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError("Only draft expenses can be submitted.")
            if not rec.product_id:
                raise UserError("You cannot submit an expense without a category.")
            rec.write({
                'state': 'finance_approval',
                'approval_state': 'submitted',
            })

    def action_hr_approve(self):
        for rec in self:
            if rec.state != 'hr_approval':
                raise UserError("Expense must be in HR Approval state.")
            rec.write({
                'state': 'approved',
                'approval_state': 'approved',
                'approval_date': fields.Datetime.now(),
            })

    def action_finance_approved(self):
        for rec in self:
            if rec.state != 'finance_approval':
                raise UserError("Expense must be in Finance Approval state.")
            rec.write({
                'state': 'hr_approval',
                'approval_state': 'submitted',
            })

    def action_refuse(self):
        for rec in self:
            rec.write({
                'state': 'refused',
                'approval_state': 'refused',
            })

    def _do_reset_approval(self):
        super()._do_reset_approval()
        self.write({'state': 'draft'})

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

            if rec.state == 'hr_approval':
                template = self.env.ref(
                    'portal_employee_expense.email_template_hr',
                    raise_if_not_found=False
                )
            elif rec.state == 'finance_approval':
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
                email_values = {}
                attachments = self.env['ir.attachment'].sudo().search([
                    ('res_model', '=', 'hr.expense'),
                    ('res_id', '=', rec.id)
                ])
                if attachments:
                    email_values['attachment_ids'] = [
                        (6, 0, attachments.ids)
                    ]
                try:
                    template.send_mail(
                        rec.id,
                        force_send=False,
                        email_values=email_values or None
                    )
                except Exception as e:
                    _logger.warning(
                        "Failed to send expense email for %s: %s",
                        rec.id,
                        e
                    )


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_post(self):
        res = super().action_post()
        if self.expense_ids:
            self.expense_ids._compute_state()
        return res


class HrExpensePostWizard(models.TransientModel):
    _inherit = 'hr.expense.post.wizard'

    def action_post_entry(self):
        # Ensure company_paid_move_ids is a list to avoid list + tuple concatenation error
        if not isinstance(self.env.context.get('company_paid_move_ids'), list):
            self = self.with_context(company_paid_move_ids=list(self.env.context.get('company_paid_move_ids') or []))
        res = super().action_post_entry()
        expenses = self.env['hr.expense'].browse(self.env.context.get('active_ids', []))
        if expenses:
            expenses._compute_state()
        return res
