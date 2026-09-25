# -*- coding: utf-8 -*-
import werkzeug.exceptions

from odoo import models
from odoo.http import request

# Portal pages that stay reachable while the portal is locked.
_ALLOWED_PREFIXES = ('/my/policies', '/my/security', '/my/account', '/my/counters')


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _pre_dispatch(cls, rule, args):
        super()._pre_dispatch(rule, args)
        path = request.httprequest.path
        if (path == '/my' or path.startswith('/my/')) and not path.startswith(_ALLOWED_PREFIXES) \
                and request.httprequest.method == 'GET' and rule.endpoint.routing.get('type') == 'http':
            user = request.env.user
            if user and not user._is_public() and cls._policy_portal_locked(user):
                werkzeug.exceptions.abort(request.redirect('/my/policies?locked=1'))

    @classmethod
    def _policy_portal_locked(cls, user):
        return bool(request.env['hr.policy.acknowledgement'].sudo().search_count([
            ('user_id', '=', user.id),
            ('state', '=', 'overdue'),
            ('policy_id.block_portal_until_ack', '=', True),
        ], limit=1))
