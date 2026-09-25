# -*- coding: utf-8 -*-
import base64
from urllib.parse import quote

from markupsafe import Markup, escape

from odoo import http, fields
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from odoo.addons.bxi_antitrust_compliance.models.antitrust_incident import MEETING_TYPES
from odoo.addons.bxi_antitrust_compliance.models.antitrust_interaction import INTERACTION_TYPES


class CompliancePortal(http.Controller):

    def _get_employee(self):
        user = request.env.user
        return request.env['hr.employee'].sudo().search([
            '|', ('user_id', '=', user.id), ('work_email', '=ilike', user.email or user.login),
        ], limit=1)

    def _attachments(self, field, model, res_id):
        attachments = request.env['ir.attachment'].sudo()
        for upload in request.httprequest.files.getlist(field):
            content = upload.read() if upload and upload.filename else b''
            if content:
                attachments |= attachments.create({
                    'name': upload.filename, 'datas': base64.b64encode(content),
                    'res_model': model, 'res_id': res_id,
                })
        return attachments

    @staticmethod
    def _text_to_html(text):
        return Markup('<p>%s</p>') % Markup('<br/>').join(escape(line) for line in (text or '').splitlines())

    def _render_form(self, template, post, error=None, **values):
        return request.render(template, dict(values, post=post, error=error, page_name='compliance'))

    @http.route('/my/compliance', type='http', auth='user', website=True)
    def portal_compliance(self, **kwargs):
        employee = self._get_employee()
        domain = [('employee_id', '=', employee.id)] if employee else [('id', '=', 0)]
        return request.render('bxi_antitrust_compliance.portal_compliance', {
            'employee': employee,
            'queries': request.env['antitrust.query'].sudo().search(domain),
            'incidents': request.env['antitrust.incident'].sudo().search(domain),
            'interactions': request.env['antitrust.interaction'].sudo().search(domain),
            'contact_email': request.env['antitrust.mixin']._contact_email(),
            'message': kwargs.get('message'),
            'page_name': 'compliance',
        })

    @http.route('/my/compliance/query', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_query(self, **post):
        employee = self._get_employee()
        if not employee:
            raise request.not_found()
        template = 'bxi_antitrust_compliance.portal_query_form'
        if request.httprequest.method != 'POST':
            return self._render_form(template, post)
        try:
            if not (post.get('subject') or '').strip() or not (post.get('situation') or '').strip():
                raise UserError(request.env._("Please fill in the subject and the situation."))
            with request.env.cr.savepoint():
                query = request.env['antitrust.query'].sudo().create({
                    'employee_id': employee.id,
                    'subject': post['subject'].strip(),
                    'situation': self._text_to_html(post['situation']),
                    'urgency': 'urgent' if post.get('urgency') == 'urgent' else 'normal',
                })
                query.attachment_ids = self._attachments('attachments', query._name, query.id)
                query.action_submit()
        except (UserError, ValidationError) as error:
            return self._render_form(template, post, error.args[0])
        return request.redirect('/my/compliance?message=' + quote(request.env._("Your query was sent to compliance.")))

    @http.route('/my/compliance/incident', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_incident(self, **post):
        employee = self._get_employee()
        if not employee:
            raise request.not_found()
        template = 'bxi_antitrust_compliance.portal_incident_form'
        values = {
            'meeting_types': MEETING_TYPES,
            'topics': request.env['antitrust.topic'].sudo().search([]),
        }
        if request.httprequest.method != 'POST':
            return self._render_form(template, post, **values)
        form = request.httprequest.form
        try:
            required = ('meeting_title', 'other_parties', 'description', 'incident_date')
            if any(not (post.get(field) or '').strip() for field in required):
                raise UserError(request.env._("Please fill in the meeting, the people present, the date and what happened."))
            with request.env.cr.savepoint():
                incident = request.env['antitrust.incident'].sudo().create({
                    'employee_id': employee.id,
                    'incident_date': post['incident_date'],
                    'meeting_title': post['meeting_title'].strip(),
                    'meeting_type': post.get('meeting_type') if post.get('meeting_type') in dict(MEETING_TYPES) else 'other',
                    'other_parties': post['other_parties'].strip(),
                    'topic_ids': [(6, 0, [int(t) for t in form.getlist('topic_ids') if t.isdigit()])],
                    'reservation_stated': post.get('reservation_stated') or False,
                    'discussion_stopped': post.get('discussion_stopped') or False,
                    'left_meeting': post.get('left_meeting') or False,
                    'departure_recorded': post.get('departure_recorded') or False,
                    'departure_record_note': post.get('departure_record_note') or False,
                    'explanation': post.get('explanation') or False,
                    'description': self._text_to_html(post['description']),
                })
                incident.attachment_ids = self._attachments('attachments', incident._name, incident.id)
                incident.action_report()
        except (UserError, ValidationError) as error:
            return self._render_form(template, post, error.args[0], **values)
        return request.redirect('/my/compliance?message=' + quote(request.env._("Your incident report was sent to compliance.")))

    @http.route('/my/compliance/interaction', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_interaction(self, **post):
        employee = self._get_employee()
        if not employee:
            raise request.not_found()
        template = 'bxi_antitrust_compliance.portal_interaction_form'
        values = {
            'interaction_types': INTERACTION_TYPES,
            'topics': request.env['antitrust.topic'].sudo().search([('category', '=', 'discussion')]),
        }
        if request.httprequest.method != 'POST':
            return self._render_form(template, post, **values)
        try:
            required = ('event_date', 'organisations', 'purpose')
            if any(not (post.get(field) or '').strip() for field in required):
                raise UserError(request.env._("Please fill in the date, the organisations and the purpose."))
            with request.env.cr.savepoint():
                interaction = request.env['antitrust.interaction'].sudo().create({
                    'employee_id': employee.id,
                    'interaction_type': post.get('interaction_type') if post.get('interaction_type') in dict(INTERACTION_TYPES) else 'other',
                    'event_date': post['event_date'],
                    'organisations': post['organisations'].strip(),
                    'purpose': post['purpose'].strip(),
                    'agenda': post.get('agenda') or False,
                    'commit_no_topics': bool(post.get('commit_no_topics')),
                    'commit_report': bool(post.get('commit_report')),
                })
                interaction.attachment_ids = self._attachments('attachments', interaction._name, interaction.id)
                interaction.action_submit()
        except (UserError, ValidationError) as error:
            return self._render_form(template, post, error.args[0], **values)
        return request.redirect('/my/compliance?message=' + quote(request.env._("Your declaration was submitted.")))

    @http.route('/my/compliance/interaction/<int:interaction_id>/confirm', type='http', auth='user',
                website=True, methods=['POST'])
    def portal_interaction_confirm(self, interaction_id, **post):
        employee = self._get_employee()
        interaction = request.env['antitrust.interaction'].sudo().browse(interaction_id).exists()
        if not interaction or interaction.employee_id != employee:
            raise request.not_found()
        try:
            interaction.action_confirm_no_issue()
        except UserError as error:
            return request.redirect('/my/compliance?message=' + quote(error.args[0]))
        return request.redirect('/my/compliance?message=' + quote(request.env._("Thank you for confirming.")))
