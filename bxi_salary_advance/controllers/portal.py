import base64
from urllib.parse import quote

from odoo import http
from odoo.exceptions import UserError, ValidationError
from odoo.http import content_disposition, request

CATEGORY_FIELDS = {
    'non_processing': {'nonprocessing_reason': 'joining'},
    'emergency': {'emergency_type': 'other'},
    'housing': {'tenancy_months': 12},
}


class SalaryAdvancePortal(http.Controller):

    # ── Helpers ──────────────────────────────────────────────────────────
    def _get_employee(self):
        user = request.env.user
        return request.env['hr.employee'].sudo().search([
            '|', ('user_id', '=', user.id),
            ('work_email', '=ilike', user.email or user.login),
        ], limit=1)

    def _get_own_advance(self, employee, advance_id):
        advance = request.env['bxi.salary.advance'].sudo().browse(advance_id).exists()
        if not employee or not advance or advance.employee_id != employee:
            raise request.not_found()
        return advance

    def _create_attachments(self, files, res_model, res_id):
        attachments = request.env['ir.attachment'].sudo()
        for upload in files:
            if upload and upload.filename:
                content = upload.read()
                if content:
                    attachments |= attachments.create({
                        'name': upload.filename,
                        'datas': base64.b64encode(content),
                        'res_model': res_model,
                        'res_id': res_id,
                    })
        return attachments

    def _get_category_issues(self, employee):
        """Eligibility problems of the employee per category, before any amount is entered."""
        Advance = request.env['bxi.salary.advance'].sudo()
        issues = {}
        for category, extra in CATEGORY_FIELDS.items():
            probe = Advance.new(dict(
                extra, employee_id=employee.id, company_id=employee.company_id.id,
                category=category, amount_requested=1.0))
            issues[category] = probe._get_eligibility_issues(check_documents=False)
        return issues

    def _form_values(self, employee, post):
        Advance = request.env['bxi.salary.advance'].sudo()
        limit = Advance._get_param('limit_percent', 75)
        monthly_salary = employee._sa_get_monthly_salary()
        currency = employee.company_id.currency_id
        return {
            'employee': employee,
            'post': post,
            'page_name': 'salary_advances',
            'categories': Advance._fields['category']._description_selection(request.env),
            'emergency_types': Advance._fields['emergency_type']._description_selection(request.env),
            'nonprocessing_reasons': Advance._fields['nonprocessing_reason']._description_selection(request.env),
            'tenancies': Advance._get_housing_tenancies(),
            'limit_percent': int(limit),
            'max_eligible': currency.round(monthly_salary * limit / 100),
            'currency': currency,
            'category_issues': self._get_category_issues(employee),
            'has_blank_form': bool(employee.company_id.sa_request_form),
            'form_optional': Advance._get_bool_param('request_form_optional'),
            'policy_status': employee._sa_get_policy_status(create=True),
        }

    def _redirect_error(self, advance, error):
        message = error.args[0] if error.args else str(error)
        return request.redirect(f'/my/salary-advances/{advance.id}?error={quote(message)}')

    # ── Pages ────────────────────────────────────────────────────────────
    @http.route('/my/salary-advances', type='http', auth='user', website=True)
    def portal_my_salary_advances(self, **kwargs):
        employee = self._get_employee()
        advances = request.env['bxi.salary.advance'].sudo().search(
            [('employee_id', '=', employee.id)]) if employee else request.env['bxi.salary.advance']
        values = {
            'employee': employee,
            'advances': advances,
            'outstanding': sum(advances.filtered(lambda a: a.state in ('disbursed', 'fnf')).mapped('amount_balance')),
            'currency': employee.company_id.currency_id if employee else request.env.company.currency_id,
            'has_blank_form': bool(employee and employee.company_id.sa_request_form),
            'page_name': 'salary_advances',
            'policy_status': employee._sa_get_policy_status(create=True) if employee else False,
        }
        return request.render('bxi_salary_advance.portal_my_salary_advances', values)

    @http.route('/my/salary-advances/new', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_new_salary_advance(self, **post):
        employee = self._get_employee()
        if not employee:
            raise request.not_found()
        template = 'bxi_salary_advance.portal_salary_advance_form'
        values = self._form_values(employee, post)
        if request.httprequest.method != 'POST':
            return request.render(template, values)

        category = post.get('category')
        vals = {
            'employee_id': employee.id,
            'company_id': employee.company_id.id,
            'category': category,
            'reason': (post.get('reason') or '').strip() or False,
        }
        try:
            vals['amount_requested'] = float(post.get('amount_requested') or 0)
            if category == 'non_processing':
                vals['nonprocessing_reason'] = post.get('nonprocessing_reason') or False
            elif category == 'emergency':
                vals['emergency_type'] = post.get('emergency_type') or False
            elif category == 'housing':
                vals['tenancy_months'] = int(post.get('tenancy_months') or 0)
            else:
                raise UserError(request.env._("Select the salary advance category."))
            with request.env.cr.savepoint():
                advance = request.env['bxi.salary.advance'].sudo().create(vals)
                files = request.httprequest.files
                request_form = self._create_attachments(files.getlist('request_form'), advance._name, advance.id)
                rental = self._create_attachments(files.getlist('rental_agreement'), advance._name, advance.id)
                advance.write({
                    'request_form_ids': [(4, att.id) for att in request_form],
                    'rental_agreement_ids': [(4, att.id) for att in rental],
                })
                if post.get('submit_now'):
                    advance.action_submit()
        except (UserError, ValidationError, ValueError) as error:
            values['error'] = error.args[0] if error.args else str(error)
            return request.render(template, values)
        return request.redirect(f'/my/salary-advances/{advance.id}')

    @http.route('/my/salary-advances/<int:advance_id>', type='http', auth='user', website=True)
    def portal_salary_advance(self, advance_id, **kwargs):
        employee = self._get_employee()
        advance = self._get_own_advance(employee, advance_id)
        values = {
            'advance': advance,
            'page_name': 'salary_advances',
            'error': kwargs.get('error'),
            'issues': advance._get_eligibility_issues() if advance.state == 'draft' else [],
            'has_blank_form': bool(advance.company_id.sa_request_form),
            'sign_url': advance._get_portal_sign_url(),
        }
        return request.render('bxi_salary_advance.portal_salary_advance', values)

    @http.route('/my/salary-advances/<int:advance_id>/documents', type='http', auth='user', website=True,
                methods=['POST'])
    def portal_salary_advance_documents(self, advance_id, **post):
        employee = self._get_employee()
        advance = self._get_own_advance(employee, advance_id)
        if advance.state != 'draft':
            return request.redirect(f'/my/salary-advances/{advance.id}')
        files = request.httprequest.files
        request_form = self._create_attachments(files.getlist('request_form'), advance._name, advance.id)
        rental = self._create_attachments(files.getlist('rental_agreement'), advance._name, advance.id)
        advance.write({
            'request_form_ids': [(4, att.id) for att in request_form],
            'rental_agreement_ids': [(4, att.id) for att in rental],
        })
        return request.redirect(f'/my/salary-advances/{advance.id}')

    @http.route('/my/salary-advances/<int:advance_id>/submit', type='http', auth='user', website=True,
                methods=['POST'])
    def portal_salary_advance_submit(self, advance_id, **post):
        employee = self._get_employee()
        advance = self._get_own_advance(employee, advance_id)
        try:
            with request.env.cr.savepoint():
                advance.action_submit()
        except (UserError, ValidationError) as error:
            return self._redirect_error(advance, error)
        return request.redirect(f'/my/salary-advances/{advance.id}')

    @http.route('/my/salary-advances/<int:advance_id>/cancel', type='http', auth='user', website=True,
                methods=['POST'])
    def portal_salary_advance_cancel(self, advance_id, **post):
        employee = self._get_employee()
        advance = self._get_own_advance(employee, advance_id)
        try:
            advance.action_cancel()
        except UserError as error:
            return self._redirect_error(advance, error)
        return request.redirect('/my/salary-advances')

    @http.route('/my/salary-advances/<int:advance_id>/request-form', type='http', auth='user', website=True)
    def portal_salary_advance_request_form(self, advance_id, **kwargs):
        employee = self._get_employee()
        advance = self._get_own_advance(employee, advance_id)
        pdf, _report_type = request.env['ir.actions.report'].sudo()._render_qweb_pdf(
            'bxi_salary_advance.action_report_salary_advance_request', advance.ids)
        filename = f"{advance.name.replace('/', '-')} - Advance Request Form.pdf"
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf)),
            ('Content-Disposition', content_disposition(filename)),
        ])

    @http.route('/my/salary-advances/blank-form', type='http', auth='user', website=True)
    def portal_salary_advance_blank_form(self, **kwargs):
        employee = self._get_employee()
        company = employee.company_id if employee else request.env.company.sudo()
        if not company.sa_request_form:
            raise request.not_found()
        content = base64.b64decode(company.sa_request_form)
        filename = company.sa_request_form_filename or 'Advance Request Form.pdf'
        return request.make_response(content, headers=[
            ('Content-Type', 'application/octet-stream'),
            ('Content-Length', len(content)),
            ('Content-Disposition', content_disposition(filename)),
        ])
