import base64
from urllib.parse import quote

from odoo import fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import content_disposition, request

COST_CATEGORIES = ('fee', 'lodging', 'material', 'travel', 'other')


class TrainingPortal(http.Controller):

    # ── Helpers ──────────────────────────────────────────────────────────
    def _get_employee(self):
        user = request.env.user
        return request.env['hr.employee'].sudo().search([
            '|', ('user_id', '=', user.id),
            ('work_email', '=ilike', user.email or user.login),
        ], limit=1)

    def _get_nominable_employees(self):
        return request.env['hr.employee'].sudo()._trn_department_employees(request.env.user)

    def _get_training(self, employee, training_id, own_only=False):
        """A training of the employee, or one they nominated or head the department of."""
        training = request.env['bxi.training.request'].sudo().browse(training_id).exists()
        if not employee or not training:
            raise request.not_found()
        if training.employee_id == employee:
            return training
        if not own_only and (training.nominated_by_id == employee
                             or training.department_id.manager_id == employee
                             or training.employee_id in self._get_nominable_employees()):
            return training
        raise request.not_found()

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

    def _redirect_error(self, training, error):
        message = error.args[0] if error.args else str(error)
        return request.redirect(f'/my/trainings/{training.id}?error={quote(message)}')

    # ── Lists ────────────────────────────────────────────────────────────
    @http.route('/my/trainings', type='http', auth='user', website=True)
    def portal_my_trainings(self, **kwargs):
        employee = self._get_employee()
        Training = request.env['bxi.training.request'].sudo()
        team = self._get_nominable_employees()
        values = {
            'employee': employee,
            'trainings': Training.search([('employee_id', '=', employee.id)]) if employee else Training,
            'nominations': Training.search([
                ('employee_id', 'in', team.ids), ('employee_id', '!=', employee.id),
            ]) if team else Training,
            'can_nominate': bool(team),
            'policy_status': employee._trn_get_policy_status() if employee else False,
            'page_name': 'trainings',
        }
        return request.render('bxi_training_policy.portal_my_trainings', values)

    @http.route('/my/training-agreements', type='http', auth='user', website=True)
    def portal_my_training_agreements(self, **kwargs):
        employee = self._get_employee()
        Agreement = request.env['bxi.training.agreement'].sudo()
        values = {
            'employee': employee,
            'agreements': Agreement.search([
                ('employee_id', '=', employee.id), ('state', 'not in', ('draft', 'cancelled')),
            ]) if employee else Agreement,
            'page_name': 'training_agreements',
        }
        return request.render('bxi_training_policy.portal_my_training_agreements', values)

    # ── Nomination (Department Heads) ────────────────────────────────────
    @http.route('/my/trainings/nominate', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_training_nominate(self, **post):
        employee = self._get_employee()
        team = self._get_nominable_employees()
        if not employee or not team:
            raise request.not_found()
        Training = request.env['bxi.training.request'].sudo()
        values = {
            'employee': employee,
            'team': team,
            'post': post,
            'categories': request.env['bxi.training.cost.line']._fields['category']._description_selection(request.env),
            'lead_days': int(Training._get_param('lead_days', 20)),
            'threshold': Training._get_agreement_threshold(),
            'currency': employee.company_id.currency_id,
            'page_name': 'trainings',
        }
        template = 'bxi_training_policy.portal_training_nominate'
        if request.httprequest.method != 'POST':
            return request.render(template, values)
        form = request.httprequest.form
        try:
            nominee = request.env['hr.employee'].sudo().browse(int(post.get('employee_id') or 0))
            if nominee not in team:
                raise UserError(request.env._("Select an employee of your department."))
            cost_lines = []
            rows = zip(form.getlist('category[]'), form.getlist('description[]'),
                       form.getlist('paid_by[]'), form.getlist('amount[]'))
            for category, description, paid_by, amount in rows:
                amount = float(amount or 0)
                if amount <= 0:
                    continue
                if category not in COST_CATEGORIES or paid_by not in ('company', 'employee'):
                    raise UserError(request.env._("Invalid cost line."))
                cost_lines.append((0, 0, {
                    'category': category, 'description': description or False,
                    'paid_by': paid_by, 'estimated_amount': amount,
                }))
            with request.env.cr.savepoint():
                training = Training.create({
                    'employee_id': nominee.id,
                    'nominated_by_id': employee.id,
                    'training_name': (post.get('training_name') or '').strip(),
                    'location': (post.get('location') or '').strip(),
                    'scope': post.get('scope') if post.get('scope') in ('domestic', 'international') else 'domestic',
                    'purpose': (post.get('purpose') or '').strip(),
                    'project_ref': (post.get('project_ref') or '').strip() or False,
                    'start_date': post.get('start_date') or False,
                    'end_date': post.get('end_date') or False,
                    'short_notice_reason': (post.get('short_notice_reason') or '').strip() or False,
                    'cost_line_ids': cost_lines,
                })
                if post.get('provider'):
                    training.provider_id = request.env['res.partner'].sudo().create({
                        'name': post['provider'].strip(), 'is_company': True})
                if post.get('submit_now'):
                    training.action_submit()
        except (UserError, ValidationError, ValueError) as error:
            values['error'] = error.args[0] if error.args else str(error)
            return request.render(template, values)
        return request.redirect(f'/my/trainings/{training.id}')

    # ── Training page ────────────────────────────────────────────────────
    @http.route('/my/trainings/<int:training_id>', type='http', auth='user', website=True)
    def portal_training(self, training_id, **kwargs):
        employee = self._get_employee()
        training = self._get_training(employee, training_id)
        is_own = training.employee_id == employee
        agreement = training.agreement_ids.filtered(lambda a: a.state in ('issued', 'submitted'))[:1] \
            or training.agreement_id
        values = {
            'training': training,
            'agreement': agreement,
            'is_own': is_own,
            'can_submit': not is_own and training.state == 'draft',
            'sign_url': training._get_portal_sign_url() if is_own else False,
            'agreement_sign_url': agreement._get_portal_sign_url() if is_own and agreement else False,
            'products': request.env['product.product'].sudo().search([('is_training_expense', '=', True)]),
            'policy_status': training.employee_id._trn_get_policy_status() if is_own else False,
            'today': fields.Date.context_today(training),
            'error': kwargs.get('error'),
            'page_name': 'trainings',
        }
        return request.render('bxi_training_policy.portal_training', values)

    @http.route('/my/trainings/<int:training_id>/submit', type='http', auth='user', website=True, methods=['POST'])
    def portal_training_submit(self, training_id, **post):
        employee = self._get_employee()
        training = self._get_training(employee, training_id)
        if training.employee_id == employee or not training._user_can_nominate(request.env.user):
            raise request.not_found()
        try:
            with request.env.cr.savepoint():
                training.action_submit()
        except (UserError, ValidationError) as error:
            return self._redirect_error(training, error)
        return request.redirect(f'/my/trainings/{training.id}')

    # ── Service agreement ────────────────────────────────────────────────
    @http.route('/my/trainings/<int:training_id>/agreement/<int:agreement_id>/download', type='http',
                auth='user', website=True)
    def portal_training_agreement_download(self, training_id, agreement_id, **kwargs):
        employee = self._get_employee()
        training = self._get_training(employee, training_id, own_only=True)
        agreement = training.agreement_ids.filtered(lambda a: a.id == agreement_id)
        if not agreement:
            raise request.not_found()
        attachment = agreement.template_attachment_id
        pdf = attachment.raw if attachment else agreement._get_template_pdf()
        filename = attachment.name if attachment else f"{agreement.name} - Service Agreement.pdf"
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf)),
            ('Content-Disposition', content_disposition(filename)),
        ])

    @http.route('/my/trainings/<int:training_id>/agreement/<int:agreement_id>', type='http', auth='user',
                website=True, methods=['POST'])
    def portal_training_agreement_upload(self, training_id, agreement_id, **post):
        employee = self._get_employee()
        training = self._get_training(employee, training_id, own_only=True)
        agreement = training.agreement_ids.filtered(lambda a: a.id == agreement_id and a.state == 'issued')
        if not agreement:
            return request.redirect(f'/my/trainings/{training.id}')
        try:
            with request.env.cr.savepoint():
                scans = self._create_attachments(request.httprequest.files.getlist('scan'), agreement._name, agreement.id)
                agreement.write({
                    'stamp_paper_no': (post.get('stamp_paper_no') or '').strip() or False,
                    'stamp_paper_value': float(post.get('stamp_paper_value') or 0),
                    'stamp_paper_date': post.get('stamp_paper_date') or False,
                    'witness1_name': (post.get('witness1_name') or '').strip() or False,
                    'witness2_name': (post.get('witness2_name') or '').strip() or False,
                    'notary_name': (post.get('notary_name') or '').strip() or False,
                    'notary_reg_no': (post.get('notary_reg_no') or '').strip() or False,
                    'notarised_date': post.get('notarised_date') or False,
                    'executed_scan_ids': [(4, att.id) for att in scans],
                })
                agreement.action_submit_execution()
        except (UserError, ValidationError, ValueError, AccessError) as error:
            return self._redirect_error(training, error)
        return request.redirect(f'/my/trainings/{training.id}')

    # ── Claim ────────────────────────────────────────────────────────────
    @http.route('/my/trainings/<int:training_id>/claim', type='http', auth='user', website=True, methods=['POST'])
    def portal_training_claim(self, training_id, **post):
        employee = self._get_employee()
        training = self._get_training(employee, training_id, own_only=True)
        if training.state != 'completed':
            return request.redirect(f'/my/trainings/{training.id}')
        form = request.httprequest.form
        files = request.httprequest.files
        Product = request.env['product.product'].sudo()
        allowed = set(Product.search([('is_training_expense', '=', True)]).ids)
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
                    if product_id not in allowed:
                        raise UserError(request.env._(
                            "Training costs are claimed under the \"Specialized Training\" categories only."))
                    lines.append(({
                        'name': description or Product.browse(product_id).name,
                        'product_id': product_id,
                        'total_amount_currency': amount,
                        'employee_id': employee.id,
                        'company_id': training.company_id.id,
                        'date': training.actual_end_date or fields.Date.context_today(training),
                        'training_request_id': training.id,
                        'payment_mode': 'own_account',
                    }, receipts[index] if index < len(receipts) else None))
                training.expense_ids.filtered(lambda exp: exp.state == 'draft').unlink()
                for vals, upload in lines:
                    expense = request.env['hr.expense'].sudo().create(vals)
                    receipt = self._create_attachments([upload], 'hr.expense', expense.id)
                    if receipt:
                        expense.message_main_attachment_id = receipt[:1].id
                training.action_submit_claim()
        except (UserError, ValidationError, ValueError) as error:
            return self._redirect_error(training, error)
        return request.redirect(f'/my/trainings/{training.id}')
