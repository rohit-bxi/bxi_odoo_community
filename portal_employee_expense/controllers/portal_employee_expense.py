import base64

from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError
from odoo.addons.portal.controllers.portal import pager as portal_pager



class EmployeePortalExpense(http.Controller):

    @http.route(['/my/employee-expenses', '/my/employee-expenses/page/<int:page>'], type='http', auth='user', website=True)
    def portal_employee_expenses(self, page=1, **kwargs):
        user = request.env.user
        Expense = request.env['hr.expense'].sudo()

        # Find employee linked to current user by user_id or email
        employees = request.env['hr.employee'].sudo().search([
            '|', ('user_id', '=', user.id),
            ('work_email', '=ilike', user.email or user.login)
        ])
        emp_ids = employees.ids

        if emp_ids:
            domain = [
                '|', ('employee_id', 'in', emp_ids),
                ('create_uid', '=', user.id)
            ]
        else:
            domain = [('create_uid', '=', user.id)]

        expense_count = Expense.search_count(domain)

        pager = portal_pager(
            url='/my/employee-expenses',
            total=expense_count,
            page=page,
            step=10
        )

        expenses = Expense.search(
            domain,
            order='date desc, id desc',
            limit=10,
            offset=pager['offset']
        )

        values = {
            'expenses': expenses,
            'page_name': 'expense',
            'pager': pager,
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
            products = request.env['product.product'].sudo().search([('can_be_expensed', '=', True)])
            if not products:
                products = request.env['product.product'].sudo().search([])
            return request.render(
                'portal_employee_expense.portal_submit_expense_template',
                {
                    'products': products,
                    'no_employee': not bool(employee),
                }
            )

        # Handle form submission (POST)
        form = request.httprequest.form
        files = request.httprequest.files

        names = form.getlist('name[]')
        product_ids = form.getlist('product_id[]')
        dates = form.getlist('date[]')
        amounts = form.getlist('amount[]')
        receipts = files.getlist('receipt[]') or files.getlist('receipt') or []

        company = (
            (employee.company_id if employee and employee.company_id else False)
            or user.company_id
            or request.env.company
        )

        for index, (name, product, date, amount) in enumerate(
            zip(names, product_ids, dates, amounts)
        ):
            if not name or not name.strip():
                continue

            product_id = int(product) if product else False
            if not product_id:
                continue

            try:
                amt = float(amount or 0)
            except (ValueError, TypeError):
                amt = 0.0

            if amt <= 0:
                continue

            # 1. Create expense in draft first with both amount fields populated
            expense = request.env['hr.expense'].sudo().create({
                'name': name.strip(),
                'date': date or http.request.env['hr.expense'].default_get(['date']).get('date'),
                'product_id': product_id,
                'total_amount': amt,
                'total_amount_currency': amt,
                'employee_id': employee.id if employee else False,
                'company_id': company.id,
                'currency_id': company.currency_id.id,
            })

            # 2. Attach receipt file if uploaded
            if receipts and index < len(receipts):
                rec_file = receipts[index]
                if rec_file and getattr(rec_file, 'filename', None) and rec_file.filename.strip():
                    rec_file.seek(0)
                    file_content = rec_file.read()
                    if file_content:
                        attachment = request.env['ir.attachment'].sudo().create({
                            'name': rec_file.filename,
                            'type': 'binary',
                            'datas': base64.b64encode(file_content),
                            'res_model': 'hr.expense',
                            'res_id': expense.id,
                            'mimetype': getattr(rec_file, 'content_type', False) or 'application/octet-stream',
                        })
                        expense.sudo().write({'message_main_attachment_id': attachment.id})

            # 3. Transition directly to finance_approval with all data and attachments in place
            expense.sudo().write({'state': 'finance_approval'})

        return request.redirect('/my/employee-expenses')