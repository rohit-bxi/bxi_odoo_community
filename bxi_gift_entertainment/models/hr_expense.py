import re
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .gift_request import CERTIFICATION

PARAM_PREFIX = 'bxi_gift_entertainment.'
GIFT_EXPENSE_TYPES = [
    ('gift', 'Business Gift'),
    ('entertainment', 'Client Entertainment'),
    ('donation', 'Donation'),
    ('gift_return', 'Gift Return Shipping'),
]


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    gift_expense_type = fields.Selection(
        GIFT_EXPENSE_TYPES, string='Gift Policy Expense',
        help="Claims of this category are checked against the Gift and Entertainment Policy.")


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    gift_expense_type = fields.Selection(related='product_id.product_tmpl_id.gift_expense_type')
    gift_request_id = fields.Many2one(
        'bxi.gift.request', string='Gift / Entertainment Request',
        domain="[('employee_id', '=', employee_id), ('state', 'in', ('approved', 'done'))]")
    donation_id = fields.Many2one(
        'bxi.gift.donation', string='Donation',
        domain="[('employee_id', '=', employee_id), ('state', 'in', ('approved', 'done'))]")
    gift_receipt_id = fields.Many2one(
        'bxi.gift.receipt', string='Returned Gift',
        domain="[('employee_id', '=', employee_id), ('state', '=', 'to_return')]")
    ent_client_name = fields.Char(string='Client / Organization')
    ent_date = fields.Date(string='Entertainment Date')
    ent_attendee_count = fields.Integer(string='Number of Attendees')
    ent_attendees = fields.Text(string='Attendees and Designations')
    ent_reason = fields.Text(string='Reason for Entertainment')
    includes_alcohol = fields.Boolean()
    alcohol_approved_by_id = fields.Many2one('res.users', string='Alcohol Approved By', readonly=True, copy=False)
    gift_certification = fields.Boolean(string='I Certify', help=CERTIFICATION, copy=False)
    mx_fiscal_folio = fields.Char(string='Fiscal Folio (UUID)', help="First 8 digits of the CFDI UUID (Mexico).")
    employee_country_code = fields.Char(compute='_compute_employee_country_code')

    @api.depends('employee_id')
    def _compute_employee_country_code(self):
        for expense in self:
            employee = expense.employee_id.sudo()
            country = employee.address_id.country_id or employee.company_id.country_id
            expense.employee_country_code = country.code

    @api.onchange('gift_request_id')
    def _onchange_gift_request_id(self):
        request = self.gift_request_id
        if request:
            self.ent_client_name = request.recipient_organization
            self.ent_date = request.event_date
            self.ent_attendee_count = len(request.attendee_ids)
            self.ent_attendees = '\n'.join('%s, %s' % (a.name, a.designation) for a in request.attendee_ids)
            self.ent_reason = request.purpose
            self.includes_alcohol = request.includes_alcohol

    def _gift_policy_errors(self):
        """Reasons the claim cannot be submitted under the Gift and Entertainment Policy."""
        self.ensure_one()
        errors = []
        params = self.env['ir.config_parameter'].sudo()
        if self.employee_country_code == 'MX' and not re.fullmatch(r'\d{8}', self.mx_fiscal_folio or ''):
            errors.append(_("Mexico: enter the first 8 digits of the CFDI UUID (fiscal folio)."))
        kind = self.gift_expense_type
        if not kind:
            return errors
        if not self.gift_certification:
            errors.append(_("Tick the certification for gift, entertainment and donation claims."))
        if kind in ('gift', 'entertainment'):
            request = self.gift_request_id.sudo()
            if not request or request.state not in ('approved', 'done'):
                errors.append(_("Link the approved Gift / Entertainment Request of this claim."))
            elif request.employee_id != self.employee_id:
                errors.append(_("The request belongs to another employee."))
            else:
                approved = request.currency_id._convert(
                    request.amount, self.company_currency_id, self.company_id, request.event_date)
                claimed = sum(request.expense_ids.filtered(
                    lambda e: e.id != self.id and e.state != 'refused').mapped('total_amount')) + self.total_amount
                if self.company_currency_id.compare_amounts(claimed, approved) > 0:
                    errors.append(_("The claims of %(request)s (%(claimed)s) exceed the approved value (%(approved)s).",
                                    request=request.name,
                                    claimed=self.company_currency_id.format(claimed),
                                    approved=self.company_currency_id.format(approved)))
        if kind == 'entertainment' or self.gift_request_id.request_type == 'entertainment':
            if not (self.ent_client_name and self.ent_date and self.ent_attendee_count > 0
                    and self.ent_attendees and self.ent_reason):
                errors.append(_("Entertainment claims need the client, the date, the number and the names and "
                                "designations of the attendees, and the reason."))
        if kind == 'donation':
            donation = self.donation_id.sudo()
            if not donation or donation.state not in ('approved', 'done'):
                errors.append(_("Link the approved Donation of this claim."))
            elif donation.routing != 'reimburse':
                errors.append(_("%s is paid directly by BXI through EdgeFi: it is not reimbursed.", donation.name))
            days = int(params.get_param(PARAM_PREFIX + 'donation_claim_days', 45))
            if self.date and self.date < fields.Date.context_today(self) - timedelta(days=days):
                errors.append(_("Donation claims must be raised within %s days of the bill date.", days))
        if kind == 'gift_return':
            receipt = self.gift_receipt_id.sudo()
            if not receipt or receipt.state != 'to_return':
                errors.append(_("Link the declared gift being returned."))
        return errors

    def action_submit(self):
        for expense in self:
            errors = expense._gift_policy_errors()
            if errors:
                raise UserError('\n'.join(errors))
        res = super().action_submit()
        for expense in self.filtered(lambda e: e.gift_expense_type == 'gift_return' and e.gift_receipt_id):
            expense.gift_receipt_id.sudo().write({'return_expense_id': expense.id, 'return_reference': str(expense.id)})
        return res

    def _gift_alcohol_approver(self):
        employee = self.employee_id.sudo()
        return employee.l3_head_id.user_id or employee.parent_id.user_id

    def _do_approve(self, check=True):
        for expense in self.filtered(lambda e: e.includes_alcohol and not e.alcohol_approved_by_id):
            approver = expense._gift_alcohol_approver()
            if not self.env.su and self.env.user != approver:
                raise UserError(_("Alcohol in client entertainment must be approved by %s (L3 Head or reporting "
                                  "manager).", approver.name or _("the L3 Head or reporting manager")))
            expense.sudo().alcohol_approved_by_id = self.env.user if not self.env.su else approver
        return super()._do_approve(check=check)
