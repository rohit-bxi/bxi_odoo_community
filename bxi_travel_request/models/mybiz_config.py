# -*- coding: utf-8 -*-
import requests
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class BxiMyBizConfig(models.Model):
    """
    Singleton-style configuration for MakeMyTrip myBiz corporate API.
    One active config record per company is expected.
    """
    _name = 'bxi.mybiz.config'
    _description = 'MakeMyTrip myBiz API Configuration'
    _inherit = ['mail.thread']
    _rec_name = 'name'

    name = fields.Char(
        string='Configuration Name',
        default='myBiz Integration',
        required=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        tracking=True,
    )
    active = fields.Boolean(string='Active', default=True, tracking=True)

    # ─── API Credentials ───────────────────────────────────────────
    client_id = fields.Char(
        string='Client ID',
        required=True,
        tracking=True,
        help='myBiz Client ID obtained from the myBiz Admin portal under Company Details.',
    )
    org_id = fields.Char(
        string='Organization ID',
        required=True,
        tracking=True,
        help='myBiz Organization ID (corporate account identifier).',
    )
    api_key = fields.Char(
        string='API Key / Secret',
        required=True,
        help='API secret key for authenticating requests to myBiz. Keep this confidential.',
    )
    base_url = fields.Char(
        string='API Base URL',
        default='https://mybiz.makemytrip.com/api/v1',
        required=True,
        help='Base URL for the myBiz Travel Request API endpoint.',
    )

    # ─── Push Endpoint Config ──────────────────────────────────────
    travel_request_endpoint = fields.Char(
        string='Travel Request Push Endpoint',
        default='/travelRequest/create',
        help='Path appended to Base URL for pushing travel requests.',
    )
    fetch_status_endpoint = fields.Char(
        string='Fetch Status Endpoint',
        default='/travelRequest/status',
        help='Path to poll booking/approval status from myBiz.',
    )

    # ─── Status ────────────────────────────────────────────────────
    last_test_status = fields.Char(string='Last Test Status', readonly=True)
    last_test_date = fields.Datetime(string='Last Tested At', readonly=True)

    # ─── Helpers ───────────────────────────────────────────────────

    def _get_auth_headers(self):
        """Return HTTP headers required by the myBiz API."""
        self.ensure_one()
        if not self.client_id or not self.org_id or not self.api_key:
            raise UserError(_(
                'myBiz API credentials are incomplete. '
                'Please configure Client ID, Organization ID, and API Key.'
            ))
        return {
            'Content-Type': 'application/json',
            'clientId': self.client_id,
            'orgId': self.org_id,
            'apiKey': self.api_key,
            'Accept': 'application/json',
        }

    def _get_endpoint(self, path_field='travel_request_endpoint'):
        """Build a full URL from base_url + path field."""
        self.ensure_one()
        base = self.base_url.rstrip('/')
        path = (getattr(self, path_field) or '').strip()
        if not path.startswith('/'):
            path = '/' + path
        return base + path

    # ─── Actions ───────────────────────────────────────────────────

    def action_test_connection(self):
        """Test connectivity to the myBiz API."""
        self.ensure_one()
        try:
            headers = self._get_auth_headers()
            url = self._get_endpoint('travel_request_endpoint')
            # Send a minimal OPTIONS/HEAD request to test auth
            resp = requests.head(url, headers=headers, timeout=10)
            if resp.status_code in (200, 201, 204, 400, 401, 403, 404, 405):
                # Any HTTP response means we reached the server
                if resp.status_code in (200, 201, 204):
                    status = f'✅ Connection successful (HTTP {resp.status_code})'
                    msg_type = 'success'
                elif resp.status_code in (401, 403):
                    status = f'⚠️ Authentication failed (HTTP {resp.status_code}) — check credentials'
                    msg_type = 'warning'
                else:
                    status = f'ℹ️ Server reachable — HTTP {resp.status_code} (endpoint may require POST)'
                    msg_type = 'info'
            else:
                status = f'⚠️ Unexpected response: HTTP {resp.status_code}'
                msg_type = 'warning'
        except requests.exceptions.ConnectionError:
            status = '❌ Connection refused — check Base URL and IP whitelisting'
            msg_type = 'danger'
        except requests.exceptions.Timeout:
            status = '❌ Connection timed out — server may be unreachable'
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

    @api.model
    def get_active_config(self, company_id=None):
        """Return the active myBiz config for the given (or current) company."""
        domain = [('active', '=', True)]
        if company_id:
            domain.append(('company_id', '=', company_id))
        else:
            domain.append(('company_id', '=', self.env.company.id))
        config = self.search(domain, limit=1)
        if not config:
            # Fallback: any active config
            config = self.search([('active', '=', True)], limit=1)
        return config
