# -*- coding: utf-8 -*-
import requests

from odoo import fields, models, _
from odoo.exceptions import UserError


class BxiMyBizConfig(models.Model):
    """
    Corrects bxi_travel_request's config to the real myBiz contract:
    auth is via the `partner-apikey` / `client-code` headers (not
    clientId/orgId/apiKey), and the create/recall paths are fixed
    endpoints under /corporate/v1 and /internal/corporate/v1.
    """
    _inherit = 'bxi.mybiz.config'

    # Legacy fields from bxi_travel_request are no longer required —
    # authentication now uses partner_api_key / client_code below.
    client_id = fields.Char(required=False)
    org_id = fields.Char(required=False)
    api_key = fields.Char(required=False)

    partner_api_key = fields.Char(
        string='Partner API Key',
        required=True,
        help='Value sent as the "partner-apikey" header. Issued by the myBiz team '
             'for this integration partner.',
    )
    client_code = fields.Char(
        string='Client Code',
        required=True,
        help='Value sent as the "client-code" header. Unique code issued by the '
             'myBiz team identifying this corporate client.',
    )

    base_url = fields.Char(default='https://mybiz.makemytrip.com')
    travel_request_endpoint = fields.Char(
        default='/corporate/v1/create/partner/travel-request',
        help='POST endpoint to push an approved travel request to myBiz.',
    )
    travel_request_recall_endpoint = fields.Char(
        string='Recall Endpoint',
        default='/internal/corporate/v1/update/partner/travel-request',
        help='POST endpoint used to recall (cancel) a previously pushed flight/hotel service.',
    )

    def _get_auth_headers(self):
        """Real myBiz auth headers: partner-apikey / client-code."""
        self.ensure_one()
        if not self.partner_api_key or not self.client_code:
            raise UserError(_(
                'myBiz API credentials are incomplete. '
                'Please configure the Partner API Key and Client Code.'
            ))
        return {
            'partner-apikey': self.partner_api_key,
            'client-code': self.client_code,
            'Content-Type': 'application/json',
        }

    def action_test_connection(self):
        """Test connectivity using the real create endpoint and headers."""
        self.ensure_one()
        try:
            headers = self._get_auth_headers()
            url = self._get_endpoint('travel_request_endpoint')
            resp = requests.head(url, headers=headers, timeout=10)
            if resp.status_code in (200, 201, 204):
                status = f'✅ Connection successful (HTTP {resp.status_code})'
                msg_type = 'success'
            elif resp.status_code in (401, 403):
                status = (
                    f'⚠️ Authentication failed (HTTP {resp.status_code}) — '
                    'check Partner API Key / Client Code'
                )
                msg_type = 'warning'
            elif resp.status_code in (400, 404, 405):
                status = f'ℹ️ Server reachable — HTTP {resp.status_code} (endpoint requires POST)'
                msg_type = 'info'
            else:
                status = f'⚠️ Unexpected response: HTTP {resp.status_code}'
                msg_type = 'warning'
        except requests.exceptions.ConnectionError:
            status = '❌ Connection refused — check Base URL and IP whitelisting with myBiz'
            msg_type = 'danger'
        except requests.exceptions.Timeout:
            status = '❌ Connection timed out — server may be unreachable'
            msg_type = 'danger'
        except UserError as e:
            status = f'❌ {str(e)}'
            msg_type = 'danger'
        except Exception as e:
            status = f'❌ Error: {str(e)}'
            msg_type = 'danger'

        self.write({
            'last_test_status': status,
            'last_test_date': fields.Datetime.now(),
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('myBiz Connection Test'),
                'message': status,
                'type': msg_type,
                'sticky': False,
            },
        }
