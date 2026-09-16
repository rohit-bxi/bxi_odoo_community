import base64

from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError



class EmployeePortalExpense(http.Controller):

    @http.route(['/my/employee-expenses'], type='http', auth='user', website=True)
    def portal_employee_expenses(self, **kwargs):
        user = request.env.user
        Expense = request.env['hr.expense'].sudo()

        if user.has_group('base.group_user'):
            expenses = Expense.search([])
        else:
            employee = request.env['hr.employee'].sudo().search([
                ('user_id', '=', user.id)
            ], limit=1)

            expenses = []
            if employee:
                expenses = Expense.search([
                    ('employee_id', '=', employee.id)
                ])
        values = {
            'expenses': expenses,
        }
        return request.render('portal_employee_expense.portal_my_expenses_template', values)
    
    @http.route('/my/submit-expenses', type='http', auth="user", website=True)
    def submit_expenses(self, **post):

        user = request.env.user

        employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', user.id)
        ], limit=1)

        # Render form (GET request)
        if not post:
            products = request.env['product.product'].sudo().search([])
            return request.render(
                'portal_employee_expense.portal_submit_expense_template',
                {'products': products}
            )

        # Handle form submission (POST)
        form = request.httprequest.form
        files = request.httprequest.files

        names = form.getlist('name[]')
        product_ids = form.getlist('product_id[]')
        dates = form.getlist('date[]')
        amounts = form.getlist('amount[]')

        # gather uploaded files (support 'receipt[]', 'attachment[]', 'attachment')
        attachments = []
        for key in ('receipt[]', 'receipt', 'attachment[]', 'attachment'):
            try:
                attachments.extend(files.getlist(key) or [])
            except Exception:
                continue

        for index, (name, product, date, amount) in enumerate(
            zip(names, product_ids, dates, amounts)
        ):
            if not name:
                continue

            product_id = int(product) if product else False

            request.env['hr.expense'].sudo().create({
                'name': name,
                'date': date,
                'product_id': product_id,
                'total_amount': float(amount or 0),
                'employee_id': employee.id if employee else False,
                'state': 'finance_approval',
            })

        return request.redirect('/my/employee-expenses')