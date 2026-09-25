import base64
from urllib.parse import quote

from odoo import http, fields
from odoo.exceptions import UserError, ValidationError
from odoo.http import request


class CertificationPortal(http.Controller):

    # ── Helpers ──────────────────────────────────────────────────────────
    def _get_employee(self):
        user = request.env.user
        return request.env['hr.employee'].sudo().search([
            '|', ('user_id', '=', user.id),
            ('work_email', '=ilike', user.email or user.login),
        ], limit=1)

    def _get_own_request(self, employee, request_id):
        cert_request = request.env['bxi.certification.request'].sudo().browse(request_id).exists()
        if not cert_request or cert_request.employee_id != employee:
            raise request.not_found()
        return cert_request

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

    def _render_error(self, template, values, error):
        values['error'] = error.args[0] if error.args else str(error)
        return request.render(template, values)

    # ── Pages ────────────────────────────────────────────────────────────
    @http.route('/my/certifications', type='http', auth='user', website=True)
    def portal_my_certifications(self, **kwargs):
        employee = self._get_employee()
        values = {
            'employee': employee,
            'cert_requests': request.env['bxi.certification.request'].sudo().search(
                [('employee_id', '=', employee.id)]) if employee else [],
            'agreements': request.env['bxi.service.agreement'].sudo().search(
                [('employee_id', '=', employee.id), ('state', '!=', 'cancelled')]) if employee else [],
            'inclusions': request.env['bxi.certification.inclusion'].sudo().search(
                [('employee_id', '=', employee.id)]) if employee else [],
            'page_name': 'certifications',
        }
        return request.render('bxi_certification_reimbursement.portal_my_certifications', values)

    @http.route('/my/certifications/new', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_new_certification_request(self, **post):
        employee = self._get_employee()
        if not employee:
            raise request.not_found()
        values = {
            'certifications': request.env['bxi.certification'].sudo().search(
                [('company_id', 'in', [False, employee.company_id.id])]),
            'post': post,
            'page_name': 'certifications',
        }
        template = 'bxi_certification_reimbursement.portal_certification_request_form'
        if request.httprequest.method != 'POST':
            return request.render(template, values)

        certification_id = int(post.get('certification_id') or 0)
        vals = {
            'employee_id': employee.id,
            'company_id': employee.company_id.id,
            'certification_id': certification_id or False,
            'certification_name': (post.get('certification_name') or '').strip() or False,
            'certifying_body': (post.get('certifying_body') or '').strip() or False,
            'estimated_cost': float(post.get('estimated_cost') or 0),
            'planned_exam_date': post.get('planned_exam_date') or False,
            'cost_centre_ack': bool(post.get('cost_centre_ack')),
        }
        try:
            with request.env.cr.savepoint():
                cert_request = request.env['bxi.certification.request'].sudo().create(vals)
                attachments = self._create_attachments(
                    request.httprequest.files.getlist('approval_email'), cert_request._name, cert_request.id)
                if attachments:
                    cert_request.pre_approval_attachment_ids = [(6, 0, attachments.ids)]
                cert_request.action_submit()
        except (UserError, ValidationError) as error:
            return self._render_error(template, values, error)
        return request.redirect(f'/my/certifications/{cert_request.id}')

    @http.route('/my/certifications/<int:request_id>', type='http', auth='user', website=True)
    def portal_certification_request(self, request_id, **kwargs):
        employee = self._get_employee()
        cert_request = self._get_own_request(employee, request_id)
        values = {
            'cert_request': cert_request,
            'products': request.env['product.product'].sudo().search([('is_certification_expense', '=', True)]),
            'page_name': 'certifications',
            'today': fields.Date.context_today(cert_request),
            'error': kwargs.get('error'),
        }
        return request.render('bxi_certification_reimbursement.portal_certification_request', values)

    @http.route('/my/certifications/<int:request_id>/claim', type='http', auth='user', website=True, methods=['POST'])
    def portal_certification_claim(self, request_id, **post):
        employee = self._get_employee()
        cert_request = self._get_own_request(employee, request_id)
        if cert_request.state != 'approved':
            return request.redirect(f'/my/certifications/{cert_request.id}')

        form = request.httprequest.form
        files = request.httprequest.files
        allowed_products = set(request.env['product.product'].sudo().search(
            [('is_certification_expense', '=', True)]).ids)
        try:
            with request.env.cr.savepoint():
                receipts = files.getlist('receipt[]')
                rows = zip(form.getlist('product_id[]'), form.getlist('amount[]'), form.getlist('description[]'))
                lines = []
                for index, (product, amount, description) in enumerate(rows):
                    product_id = int(product or 0)
                    amount = float(amount or 0)
                    if not product_id or amount <= 0:
                        continue
                    if product_id not in allowed_products:
                        raise UserError(request.env._("Only certification expense categories can be claimed."))
                    lines.append(({
                        'name': description or request.env['product.product'].sudo().browse(product_id).name,
                        'product_id': product_id,
                        'total_amount_currency': amount,
                        'employee_id': employee.id,
                        'company_id': cert_request.company_id.id,
                        'date': post.get('exam_clear_date') or fields.Date.context_today(cert_request),
                        'certification_request_id': cert_request.id,
                    }, receipts[index] if index < len(receipts) else None))
                cert_request.expense_ids.filtered(lambda exp: exp.state == 'draft').unlink()
                for vals, upload in lines:
                    expense = request.env['hr.expense'].sudo().create(vals)
                    receipt = self._create_attachments([upload], 'hr.expense', expense.id)
                    if receipt:
                        expense.message_main_attachment_id = receipt[:1].id
                certificate = self._create_attachments(files.getlist('certificate'), cert_request._name, cert_request.id)
                approval = self._create_attachments(files.getlist('approval_email'), cert_request._name, cert_request.id)
                cert_request.write({
                    'exam_clear_date': post.get('exam_clear_date') or False,
                    'attempt_passed': bool(post.get('attempt_passed')),
                    'certificate_attachment_ids': [(4, att.id) for att in certificate],
                    'pre_approval_attachment_ids': [(4, att.id) for att in approval],
                })
                cert_request.action_submit_claim()
        except (UserError, ValidationError, ValueError) as error:
            message = error.args[0] if error.args else str(error)
            return request.redirect(f'/my/certifications/{cert_request.id}?error={quote(message)}')
        return request.redirect(f'/my/certifications/{cert_request.id}')

    @http.route('/my/certifications/<int:request_id>/cancel', type='http', auth='user', website=True, methods=['POST'])
    def portal_certification_cancel(self, request_id, **post):
        employee = self._get_employee()
        cert_request = self._get_own_request(employee, request_id)
        try:
            cert_request.action_cancel()
        except UserError as error:
            return request.redirect(f'/my/certifications/{cert_request.id}?error={quote(error.args[0])}')
        return request.redirect('/my/certifications')

    @http.route('/my/certifications/inclusion', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_certification_inclusion(self, **post):
        employee = self._get_employee()
        if not employee:
            raise request.not_found()
        values = {
            'lobs': request.env['bxi.line.of.business'].sudo().search([]),
            'currencies': request.env['res.currency'].sudo().search([('active', '=', True)]),
            'employee': employee,
            'post': post,
            'page_name': 'certifications',
        }
        template = 'bxi_certification_reimbursement.portal_certification_inclusion_form'
        if request.httprequest.method != 'POST':
            return request.render(template, values)
        try:
            required = {
                'certification_name': request.env._("Certification name"), 'certifying_body': request.env._("Certifying body"),
                'area': request.env._("Area of certification"), 'website': request.env._("Website"), 'business_case': request.env._("Business case"),
            }
            missing = [label for field, label in required.items() if not (post.get(field) or '').strip()]
            if not (post.get('lob_id') or employee.lob_id):
                missing.append(request.env._("Line of Business"))
            if missing:
                raise UserError(request.env._("Please fill in: %(fields)s", fields=', '.join(missing)))
            with request.env.cr.savepoint():
                inclusion = request.env['bxi.certification.inclusion'].sudo().create({
                    'employee_id': employee.id,
                    'company_id': employee.company_id.id,
                    'lob_id': int(post.get('lob_id') or 0) or employee.lob_id.id,
                    'certification_name': post.get('certification_name'),
                    'version_exam_no': post.get('version_exam_no'),
                    'certifying_body': post.get('certifying_body'),
                    'area': post.get('area'),
                    'cost': float(post.get('cost') or 0),
                    'currency_id': int(post.get('currency_id') or 0) or employee.company_id.currency_id.id,
                    'information': post.get('information'),
                    'website': post.get('website'),
                    'is_du_specific': 'y' if post.get('is_du_specific') == 'y' else 'n',
                    'business_case': post.get('business_case'),
                })
                inclusion.action_submit()
        except (UserError, ValidationError, ValueError) as error:
            return self._render_error(template, values, error)
        return request.redirect('/my/certifications')
