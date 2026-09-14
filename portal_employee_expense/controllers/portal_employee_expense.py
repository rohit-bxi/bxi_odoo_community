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

        if not employee:
            raise AccessError("No employee is linked to your user account.")

        if not post:
            products = request.env['product.product'].sudo().search([])
            return request.render(
                'portal_employee_expense.portal_submit_expense_template',
                {'products': products}
            )

        form = request.httprequest.form
        files = request.httprequest.files

        names = form.getlist('name[]')
        product_ids = form.getlist('product_id[]')
        dates = form.getlist('date[]')
        amounts = form.getlist('amount[]')

        attachments = []

        for key in ('receipt[]', 'receipt', 'attachment[]', 'attachment'):
            try:
                attachments.extend(files.getlist(key) or [])
            except Exception:
                pass

        row_count = max(
            len(names),
            len(product_ids),
            len(dates),
            len(amounts),
        )

        for index in range(row_count):

            name = names[index] if index < len(names) else False
            product = product_ids[index] if index < len(product_ids) else False
            date = dates[index] if index < len(dates) else False
            amount = amounts[index] if index < len(amounts) else False

            if not name:
                continue

            product_id = int(product) if product else False

            expense_record = request.env['hr.expense'].sudo().create({
                'name': name,
                'date': date,
                'product_id': product_id,
                'total_amount': float(amount or 0),
                'employee_id': employee.id if employee else False,
                'state': 'hr_approval',
            })

            uploaded_file = (
                attachments[index]
                if index < len(attachments)
                else False
            )

            if uploaded_file and uploaded_file.filename:
                file_content = uploaded_file.read()

                if file_content:
                    attachment = request.env['ir.attachment'].sudo().create({
                        'name': uploaded_file.filename,
                        'type': 'binary',
                        'datas': base64.b64encode(file_content).decode('utf-8'),
                        'res_model': 'hr.expense',
                        'res_id': expense_record.id,
                        'mimetype': (
                            uploaded_file.content_type
                            or 'application/octet-stream'
                        ),
                    })

                    # Link receipt to expense
                    expense_record.sudo().write({
                        'attachment_ids': [(4, attachment.id)]
                    })

            expense_record.sudo().write({
                'state': 'hr_approval'
            })

            expense_record._send_state_email()
        return request.redirect('/my/employee-expenses')