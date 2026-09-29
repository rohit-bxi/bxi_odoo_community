import base64

from dateutil.relativedelta import relativedelta

from odoo import fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

from odoo.addons.bxi_local_conveyance.models.product_template import TRAVEL_KINDS, VEHICLE_KINDS


class ConveyancePortal(http.Controller):

    # ── Helpers ──────────────────────────────────────────────────────────
    def _get_employee(self):
        user = request.env.user
        return request.env['hr.employee'].sudo().search([
            '|', ('user_id', '=', user.id),
            ('work_email', '=ilike', user.email or user.login),
        ], limit=1)

    def _get_products(self, employee):
        domain = [('can_be_expensed', '=', True), ('conveyance_kind', '!=', False)]
        if not employee.is_sales_team:
            domain.append(('conveyance_kind', '!=', 'food'))
        return request.env['product.product'].sudo().search(domain, order='default_code, id')

    def _get_trip_claims(self, employee):
        """The employee's own trips parking and toll can be claimed with."""
        Expense = request.env['hr.expense'].sudo()
        claim_days = Expense._get_conveyance_param('claim_days')
        since = fields.Date.context_today(Expense) - relativedelta(days=claim_days)
        return Expense.search([
            ('employee_id', '=', employee.id), ('conveyance_kind', 'in', TRAVEL_KINDS),
            ('date', '>=', since), ('state', '!=', 'refused'),
        ], order='date desc, id desc')

    def _selection(self, field_name):
        field = request.env['hr.expense']._fields[field_name]
        return field._description_selection(request.env)

    def _form_values(self, employee, post, error=None):
        Expense = request.env['hr.expense'].sudo()
        return {
            'employee': employee,
            'products': self._get_products(employee) if employee else request.env['product.product'],
            'trip_claims': self._get_trip_claims(employee) if employee else Expense,
            'purposes': self._selection('conveyance_purpose'),
            'airport_legs': self._selection('conveyance_airport_leg'),
            'travel_plan': employee.conveyance_travel_plan_id if employee else False,
            'claim_days': Expense._get_conveyance_param('claim_days'),
            'today': fields.Date.to_string(fields.Date.context_today(Expense)),
            'currency': (employee.company_id or request.env.company).currency_id,
            'post': post,
            'error': error,
            'page_name': 'conveyance',
        }

    def _prepare_expense_vals(self, employee, post):
        _ = request.env._
        product = request.env['product.product'].sudo().browse(int(post.get('product_id') or 0))
        if product not in self._get_products(employee):
            raise UserError(_("Select the conveyance type."))
        kind = product.conveyance_kind
        try:
            date = fields.Date.to_date(post.get('date'))
            amount = float(post.get('amount') or 0)
            distance = float(post.get('distance') or 0)
        except ValueError:
            raise UserError(_("Check the date, distance and amount."))
        if not date:
            raise UserError(_("Enter the date of the travel."))
        vals = {
            'name': (post.get('name') or '').strip() or product.name,
            'product_id': product.id,
            'employee_id': employee.id,
            'company_id': employee.company_id.id,
            'date': date,
            'payment_mode': 'own_account',
            'conveyance_bill_number': (post.get('bill_number') or '').strip() or False,
        }
        if kind in TRAVEL_KINDS:
            purpose = post.get('purpose')
            if purpose not in dict(self._selection('conveyance_purpose')):
                raise UserError(_("Select the purpose of the travel."))
            vals.update({
                'conveyance_purpose': purpose,
                'conveyance_from': (post.get('from') or '').strip(),
                'conveyance_to': (post.get('to') or '').strip(),
                'conveyance_distance': distance,
                'conveyance_within_city': bool(post.get('within_city')),
                'conveyance_reason': (post.get('reason') or '').strip() or False,
                'conveyance_is_emergency': kind == 'auto' and bool(post.get('is_emergency')),
            })
            if purpose == 'airport':
                leg = post.get('airport_leg')
                vals['conveyance_airport_leg'] = leg if leg in dict(self._selection('conveyance_airport_leg')) else False
        elif kind == 'parking_toll':
            parent = request.env['hr.expense'].sudo().browse(int(post.get('parent_id') or 0))
            vals['conveyance_parent_id'] = parent.id if parent in self._get_trip_claims(employee) else False
        if kind in VEHICLE_KINDS:
            vals['quantity'] = distance
        else:
            vals['total_amount_currency'] = amount
        if kind == 'food':
            vals['conveyance_bill_amount'] = amount
        return vals

    def _attach_receipts(self, expense, files):
        Attachment = request.env['ir.attachment'].sudo()
        for upload in files:
            if upload and upload.filename:
                content = upload.read()
                if content:
                    attachment = Attachment.create({
                        'name': upload.filename,
                        'datas': base64.b64encode(content),
                        'res_model': 'hr.expense',
                        'res_id': expense.id,
                    })
                    if not expense.message_main_attachment_id:
                        expense.message_main_attachment_id = attachment

    # ── Routes ───────────────────────────────────────────────────────────
    @http.route('/my/conveyance', type='http', auth='user', website=True)
    def portal_my_conveyance(self, **kwargs):
        employee = self._get_employee()
        Expense = request.env['hr.expense'].sudo()
        values = {
            'employee': employee,
            'claims': Expense.search([
                ('employee_id', '=', employee.id), ('conveyance_kind', '!=', False),
            ], order='date desc, id desc', limit=200) if employee else Expense,
            'travel_plan': employee.conveyance_travel_plan_id if employee else False,
            'claim_days': Expense._get_conveyance_param('claim_days'),
            'submitted': kwargs.get('submitted'),
            'page_name': 'conveyance',
        }
        return request.render('bxi_local_conveyance.portal_my_conveyance', values)

    @http.route('/my/conveyance/new', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_conveyance_new(self, **post):
        employee = self._get_employee()
        template = 'bxi_local_conveyance.portal_conveyance_form'
        if request.httprequest.method != 'POST':
            return request.render(template, self._form_values(employee, {}))
        if not employee:
            raise request.not_found()
        try:
            with request.env.cr.savepoint():
                expense = request.env['hr.expense'].sudo().create(self._prepare_expense_vals(employee, post))
                self._attach_receipts(expense, request.httprequest.files.getlist('receipt'))
                expense.action_submit()
        except (UserError, ValidationError, AccessError) as error:
            message = error.args[0] if error.args else str(error)
            return request.render(template, self._form_values(employee, post, error=message))
        return request.redirect('/my/conveyance?submitted=1')
