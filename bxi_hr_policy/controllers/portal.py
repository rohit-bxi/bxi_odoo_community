# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal


class PolicyPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'policy_ack_count' in counters:
            values['policy_ack_count'] = request.env['hr.policy.acknowledgement'].sudo().search_count([
                ('user_id', '=', request.env.uid), ('state', 'in', ('pending', 'overdue')),
            ])
        return values

    def _get_own_acknowledgement(self, ack_id):
        ack = request.env['hr.policy.acknowledgement'].sudo().browse(ack_id).exists()
        if not ack or ack.user_id != request.env.user:
            raise request.not_found()
        return ack

    @http.route('/my/policies', type='http', auth='user', website=True)
    def portal_my_policies(self, locked=None, **kwargs):
        acks = request.env['hr.policy.acknowledgement'].sudo().search([
            ('user_id', '=', request.env.uid), ('state', '!=', 'cancelled'),
        ])
        return request.render('bxi_hr_policy.portal_my_policies', {
            'acks': acks,
            'locked': locked,
            'page_name': 'policies',
        })

    @http.route('/my/policies/<int:ack_id>', type='http', auth='user', website=True)
    def portal_policy(self, ack_id, error=None, **kwargs):
        ack = self._get_own_acknowledgement(ack_id)
        return request.render('bxi_hr_policy.portal_policy_acknowledgement', {
            'ack': ack,
            'error': error,
            'page_name': 'policies',
        })

    @http.route('/my/policies/<int:ack_id>/acknowledge', type='http', auth='user', website=True, methods=['POST'])
    def portal_policy_acknowledge(self, ack_id, **post):
        ack = self._get_own_acknowledgement(ack_id)
        if not post.get('agree'):
            return request.redirect(f'/my/policies/{ack.id}?error=agree')
        if not ack.document_opened:
            return request.redirect(f'/my/policies/{ack.id}?error=open')
        ack.with_user(request.env.user)._do_acknowledge(
            'portal',
            request.httprequest.remote_addr,
            request.httprequest.user_agent.string,
        )
        return request.redirect('/my/policies')
