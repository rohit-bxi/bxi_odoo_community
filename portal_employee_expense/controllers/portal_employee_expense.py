import base64

from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError



class EmployeePortalExpense(http.Controller):

    @http.route(['/my/employee-expenses'], type='http', auth='user', website=True)
    def portal_employee_expenses(self, **kwargs):
        user = request.env.user
        Expense = request.env['hr.expense'].sudo()

        # Find employee linked to current user by user_id or email
        employees = request.env['hr.employee'].sudo().search([
            '|', ('user_id', '=', user.id),
            ('work_email', '=ilike', user.email or user.login)
        ])
        emp_ids = employees.ids

        if emp_ids:
            expenses = Expense.search([
                '|', ('employee_id', 'in', emp_ids),
                ('create_uid', '=', user.id)
            ], order='date desc, id desc')
        else:
            expenses = Expense.search([
                ('create_uid', '=', user.id)
            ], order='date desc, id desc')

        values = {
            'expenses': expenses,
        }
        return request.render('portal_employee_expense.portal_my_expenses_template', values)
    
    @http.route('/my/submit-expenses', type='http', auth="user", website=True)
    def submit_expenses(self, **post):

        user = request.env.user

        employee = request.env['hr.employee'].sudo().search([
            '|', ('user_id', '=', user.id),
            ('work_email', '=ilike', user.email or user.login)
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
        receipts = files.getlist('receipt[]') or files.getlist('receipt') or []

        for index, (name, product, date, amount) in enumerate(
            zip(names, product_ids, dates, amounts)
        ):
            if not name:
                continue

            product_id = int(product) if product else False

            expense = request.env['hr.expense'].sudo().create({
                'name': name,
                'date': date,
                'product_id': product_id,
                'total_amount': float(amount or 0),
                'employee_id': employee.id if employee else False,
                'state': 'finance_approval',
            })

            if receipts and index < len(receipts):
                rec_file = receipts[index]
                if rec_file and getattr(rec_file, 'filename', None):
                    file_content = rec_file.read()
                    if file_content:
                        attachment = request.env['ir.attachment'].sudo().create({
                            'name': rec_file.filename,
                            'type': 'binary',
                            'datas': base64.b64encode(file_content),
                            'res_model': 'hr.expense',
                            'res_id': expense.id,
                        })
                        expense.sudo().write({'message_main_attachment_id': attachment.id})

        return request.redirect('/my/employee-expenses')