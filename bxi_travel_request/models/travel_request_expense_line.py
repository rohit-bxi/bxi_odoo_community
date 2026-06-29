from odoo import api, fields, models, _
from odoo.exceptions import UserError


class TravelRequestExpenseLine(models.Model):
    _name = 'travel.request.expense.line'
    _description = 'Travel Request Expense Line'
    _order = 'expense_date, id'

    travel_request_id = fields.Many2one(
        'travel.request',
        string='Travel Request',
        required=True,
        ondelete='cascade',
    )

    expense_date = fields.Date(
        string='Expense Date',
        required=True,
        default=fields.Date.context_today,
    )

    expense_type = fields.Selection([
        ('travel', 'Travel'),
        ('hotel', 'Hotel'),
        ('food', 'Food'),
        ('local_conveyance', 'Local Conveyance'),
        ('misc', 'Miscellaneous'),
    ], string='Expense Type', required=True)

    description = fields.Char(string='Description', required=True)
    amount = fields.Float(string='Amount', required=True)
    payment_mode = fields.Selection([
        ('cash', 'Cash'),
        ('card', 'Card'),
        ('upi', 'UPI'),
        ('bank', 'Bank'),
        ('company_paid', 'Company Paid'),
    ], string='Payment Mode')
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'travel_expense_attachment_rel',  # relation table
        'expense_line_id',
        'attachment_id',
        string="Attachments"
    )
    remarks = fields.Char(string='Remarks')

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount < 0:
                raise UserError(_("Amount cannot be negative."))