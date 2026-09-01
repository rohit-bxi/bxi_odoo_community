# -*- coding: utf-8 -*-
import base64
import mimetypes
from odoo import http
from odoo.http import request


class HrPolicyController(http.Controller):

    @http.route('/bxi_hr_policy/preview/<int:policy_id>', type='http', auth='user', methods=['GET'])
    def preview_policy_document(self, policy_id, **kwargs):
        """
        Stream the company policy document directly in-browser (view-only mode).
        Sends headers with Content-Disposition: inline to prevent file download prompts.
        """
        policy = request.env['hr.company.policy'].browse(policy_id)
        if not policy.exists() or not policy.policy_document:
            return request.not_found()

        # Decode file binary
        file_content = base64.b64decode(policy.policy_document)
        filename = policy.policy_filename or f"policy_{policy.id}.pdf"
        mimetype = policy.mimetype or mimetypes.guess_type(filename)[0] or 'application/pdf'

        headers = [
            ('Content-Type', mimetype),
            ('Content-Length', len(file_content)),
            ('Content-Disposition', f'inline; filename="{filename}"'),
            ('X-Frame-Options', 'SAMEORIGIN'),
            ('X-Content-Type-Options', 'nosniff'),
            ('Cache-Control', 'private, max-age=3600'),
        ]

        return request.make_response(file_content, headers=headers)
