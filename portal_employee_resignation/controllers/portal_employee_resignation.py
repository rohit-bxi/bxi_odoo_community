# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request
from datetime import datetime
import base64


class PortalEmployeeResignation(http.Controller):

    @http.route(['/my/resignations'], type='http', auth='user', website=True)
    def portal_my_resignations(self, **kwargs):
        """List all resignation requests for the logged-in employee."""
        user = request.env.user

        employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', user.id)
        ], limit=1)

        resignations = []
        if employee:
            # Reads records from the existing employee.resignation model
            resignations = request.env['employee.resignation'].sudo().search([
                ('employee_id', '=', employee.id)
            ], order='resignation_date desc')

        return request.render(
            'portal_employee_resignation.portal_my_resignations_template',
            {'resignations': resignations, 'employee': employee}
        )

    @http.route(['/my/apply-resignation'], type='http', auth='user', website=True)
    def apply_resignation(self, **post):
        """Show the apply resignation form (GET) or process it (POST)."""
        user = request.env.user

        employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', user.id)
        ], limit=1)

        # GET request — render the form
        if request.httprequest.method == 'GET':
            return request.render(
                'portal_employee_resignation.portal_apply_resignation_template',
                {'employee': employee}
            )

        # POST request — process the submission
        form = request.httprequest.form

        resignation_date = form.get('resignation_date', '').strip()
        last_working_day = form.get('last_working_day', '').strip()
        reason = form.get('reason', '').strip()
        resignation_body = form.get('resignation_body', '').strip()

        # ── Validation ────────────────────────────────────────────────
        error = None

        if not employee:
            error = 'No employee profile found for your account. Please contact HR.'
        elif not resignation_date or not last_working_day or not reason:
            error = 'Resignation Date, Last Working Day, and Reason are required.'
        elif not resignation_body:
            error = 'Please write a resignation letter before submitting.'
        else:
            # Validate that last_working_day >= resignation_date (mirrors model constraint)
            try:
                r_date = datetime.strptime(resignation_date, '%Y-%m-%d').date()
                l_date = datetime.strptime(last_working_day, '%Y-%m-%d').date()
                if l_date < r_date:
                    error = 'The Requested Last Working Day cannot be earlier than the Resignation Date.'
            except ValueError:
                error = 'Invalid date format. Please use the date picker.'

        if error:
            return request.render(
                'portal_employee_resignation.portal_apply_resignation_template',
                {'employee': employee, 'error': error}
            )

        # ── Create record in the existing employee.resignation model ──
        vals = {
            'employee_id': employee.id,
            'resignation_date': resignation_date,
            'last_working_day': last_working_day,
            'reason': reason,
            'resignation_body': resignation_body,
            # state defaults to 'draft' per model default
        }

        try:
            # Creates a record in employee.resignation (from employee_onboarding module)
            resignation = request.env['employee.resignation'].sudo().create(vals)

            # Handle attachments
            uploaded_files = request.httprequest.files.getlist('attachments')
            attachment_ids = []
            for file in uploaded_files:
                if file.filename:
                    file_content = file.read()
                    attachment = request.env['ir.attachment'].sudo().create({
                        'name': file.filename,
                        'datas': base64.b64encode(file_content),
                        'res_model': 'employee.resignation',
                        'res_id': resignation.id,
                    })
                    attachment_ids.append(attachment.id)

            if attachment_ids:
                resignation.sudo().write({
                    'attachment_ids': [(6, 0, attachment_ids)]
                })

            # Immediately transition draft → submitted (mirrors the backend workflow button)
            resignation.sudo().action_submit()
        except Exception as e:
            return request.render(
                'portal_employee_resignation.portal_apply_resignation_template',
                {
                    'employee': employee,
                    'error': 'Submission failed: %s' % str(e),
                }
            )

        return request.redirect('/my/resignations?submitted=1')
