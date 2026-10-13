import base64
from urllib.parse import quote

from odoo import fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import content_disposition, request

from odoo.addons.bxi_equitable_benefit.models.eb_rate import DEPLOYMENT, WORK_CATEGORY

# Payouts the employee sees: decided by Finance. Drafts and validations in progress may still change.
VISIBLE_PAYOUT_STATES = ('approved', 'paid')
# Assignments the employee can still withdraw.
WITHDRAWABLE_STATES = ('draft', 'submitted')


class EquitableBenefitPortal(http.Controller):

    # ── Helpers ──────────────────────────────────────────────────────────
    def _get_employee(self):
        """The employee of the user; by work email only when no employee is linked to the user, and only when
        that email is not shared, since benefits and pay must never show to someone else."""
        user = request.env.user
        Employee = request.env['hr.employee'].sudo()
        employee = Employee.search([('user_id', '=', user.id)], limit=1)
        if employee or not user.email:
            return employee
        by_email = Employee.search([('user_id', '=', False), ('work_email', '=ilike', user.email)], limit=2)
        return by_email if len(by_email) == 1 else Employee

    def _get_assignment(self, employee, assignment_id):
        assignment = request.env['bxi.eb.assignment'].sudo().browse(assignment_id).exists()
        if not employee or assignment.employee_id != employee:
            raise request.not_found()
        return assignment

    def _get_projects(self, employee):
        """Projects the employee works on: followed, with a task assigned, or on an earlier work pattern."""
        Project = request.env['project.project'].sudo()
        user = employee.user_id
        domain = [('company_id', 'in', (employee.company_id.id, False))]
        member = Project.search(domain + [
            '|', ('message_partner_ids', 'in', (employee.work_contact_id | user.partner_id).ids),
            ('task_ids.user_ids', 'in', user.ids),
        ]) if user or employee.work_contact_id else Project
        earlier = request.env['bxi.eb.assignment'].sudo().search([('employee_id', '=', employee.id)]).project_ids
        return (member | earlier).filtered('active').sorted('name')

    def _get_rates(self, employee):
        """The rate matrix valid today, for the policy summary."""
        today = fields.Date.context_today(request.env['bxi.eb.rate'])
        return request.env['bxi.eb.rate'].sudo().search([
            ('work_pattern_id.active', '=', True),
            ('company_id', 'in', (employee.company_id.id, False)),
            ('date_from', '<=', today),
            '|', ('date_to', '=', False), ('date_to', '>=', today),
        ], order='work_pattern_id, work_category, deployment')

    def _create_attachments(self, files, assignment):
        Attachment = request.env['ir.attachment'].sudo()
        attachments = Attachment
        for upload in files:
            if upload and upload.filename:
                content = upload.read()
                if content:
                    attachments |= Attachment.create({
                        'name': upload.filename,
                        'datas': base64.b64encode(content),
                        'res_model': 'bxi.eb.assignment',
                        'res_id': assignment.id,
                    })
        return attachments

    def _selection_label(self, record, field_name):
        return dict(record._fields[field_name]._description_selection(request.env)).get(record[field_name])

    # ── Overview ─────────────────────────────────────────────────────────
    @http.route('/my/equitable-benefit', type='http', auth='user', website=True)
    def portal_my_equitable_benefit(self, **kwargs):
        employee = self._get_employee()
        Assignment = request.env['bxi.eb.assignment'].sudo()
        Payout = request.env['bxi.eb.payout'].sudo()
        values = {
            'employee': employee,
            'current': employee.eb_current_assignment_id if employee else Assignment,
            'assignments': Assignment.search([('employee_id', '=', employee.id)]) if employee else Assignment,
            'payouts': Payout.search([
                ('employee_id', '=', employee.id), ('state', 'in', VISIBLE_PAYOUT_STATES),
            ]) if employee else Payout,
            'rates': self._get_rates(employee) if employee else request.env['bxi.eb.rate'],
            'withdrawable_states': WITHDRAWABLE_STATES,
            'label': self._selection_label,
            'submitted': kwargs.get('submitted'),
            'withdrawn': kwargs.get('withdrawn'),
            'error': kwargs.get('error'),
            'page_name': 'equitable_benefit',
        }
        return request.render('bxi_equitable_benefit.portal_my_equitable_benefit', values)

    # ── Declare a work pattern ───────────────────────────────────────────
    def _form_values(self, employee, post, error=None):
        return {
            'employee': employee,
            'patterns': request.env['bxi.eb.work.pattern'].sudo().search([]),
            'categories': WORK_CATEGORY,
            'deployments': DEPLOYMENT,
            'projects': self._get_projects(employee) if employee else request.env['project.project'],
            'rates': self._get_rates(employee) if employee else request.env['bxi.eb.rate'],
            'label': self._selection_label,
            'post': post,
            'selected_projects': [int(pid) for pid in request.httprequest.form.getlist('project_ids') if pid.isdigit()]
            if request.httprequest.method == 'POST' else [],
            'error': error,
            'page_name': 'equitable_benefit',
        }

    def _prepare_assignment_vals(self, employee, post):
        _ = request.env._
        pattern = request.env['bxi.eb.work.pattern'].sudo().browse(int(post.get('work_pattern_id') or 0)).exists()
        if not pattern.active:
            raise UserError(_("Select the work pattern."))
        if post.get('work_category') not in dict(WORK_CATEGORY):
            raise UserError(_("Select whether the work pattern is client aligned."))
        if post.get('deployment') not in dict(DEPLOYMENT):
            raise UserError(_("Select onsite or offshore."))
        try:
            date_from = fields.Date.to_date(post.get('date_from'))
            date_to = fields.Date.to_date(post.get('date_to') or None)
        except ValueError:
            raise UserError(_("Check the dates."))
        if not date_from:
            raise UserError(_("Enter the date the work pattern started."))
        allowed = self._get_projects(employee)
        project_ids = [int(pid) for pid in request.httprequest.form.getlist('project_ids') if pid.isdigit()]
        return {
            'employee_id': employee.id,
            'work_pattern_id': pattern.id,
            'work_category': post['work_category'],
            'deployment': post['deployment'],
            'date_from': date_from,
            'date_to': date_to,
            'project_ids': [(6, 0, allowed.filtered(lambda project: project.id in project_ids).ids)],
            'justification': (post.get('justification') or '').strip() or False,
        }

    @http.route('/my/equitable-benefit/pattern/new', type='http', auth='user', website=True,
                methods=['GET', 'POST'])
    def portal_equitable_benefit_new(self, **post):
        employee = self._get_employee()
        template = 'bxi_equitable_benefit.portal_equitable_benefit_form'
        if request.httprequest.method != 'POST':
            return request.render(template, self._form_values(employee, {}))
        if not employee:
            raise request.not_found()
        try:
            with request.env.cr.savepoint():
                # Created in the employee's name as a draft; Revenue Assurance approves it.
                assignment = request.env['bxi.eb.assignment'].sudo().create(
                    self._prepare_assignment_vals(employee, post))
                attachments = self._create_attachments(request.httprequest.files.getlist('documents'), assignment)
                if attachments:
                    assignment.requirement_attachment_ids = [(6, 0, attachments.ids)]
                assignment.action_submit()
        except (UserError, ValidationError, AccessError) as error:
            message = error.args[0] if error.args else str(error)
            return request.render(template, self._form_values(employee, post, error=message))
        return request.redirect('/my/equitable-benefit?submitted=1')

    @http.route('/my/equitable-benefit/pattern/<int:assignment_id>/withdraw', type='http', auth='user',
                website=True, methods=['POST'])
    def portal_equitable_benefit_withdraw(self, assignment_id, **post):
        employee = self._get_employee()
        assignment = self._get_assignment(employee, assignment_id)
        if assignment.state not in WITHDRAWABLE_STATES:
            message = request.env._("Only work patterns not reviewed yet can be withdrawn.")
            return request.redirect(f'/my/equitable-benefit?error={quote(message)}')
        assignment.action_cancel()
        assignment.message_post(body=request.env._("Withdrawn by the employee."))
        return request.redirect('/my/equitable-benefit?withdrawn=1')

    # ── Payout statement ─────────────────────────────────────────────────
    @http.route('/my/equitable-benefit/payout/<int:payout_id>/statement', type='http', auth='user', website=True)
    def portal_equitable_benefit_statement(self, payout_id, **kwargs):
        employee = self._get_employee()
        payout = request.env['bxi.eb.payout'].sudo().browse(payout_id).exists()
        if not employee or payout.employee_id != employee or payout.state not in VISIBLE_PAYOUT_STATES:
            raise request.not_found()
        pdf, _type = request.env['ir.actions.report'].sudo()._render_qweb_pdf(
            'bxi_equitable_benefit.action_report_bxi_eb_payout_statement', payout.ids)
        filename = f"Equitable Benefit - {payout.fy_name}.pdf"
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf)),
            ('Content-Disposition', content_disposition(filename)),
        ])
