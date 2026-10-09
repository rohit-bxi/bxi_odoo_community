# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMybizConfigIntegration(TransactionCase):
    """Tests for the corrected myBiz config: real headers and endpoints."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['bxi.mybiz.config'].create({
            'name': 'Real Contract Config',
            'partner_api_key': 'PARTNER-KEY-1',
            'client_code': 'CLIENT-CODE-1',
        })

    def test_defaults_match_real_contract(self):
        self.assertEqual(self.config.base_url, 'https://mybiz.makemytrip.com')
        self.assertEqual(
            self.config.travel_request_endpoint,
            '/corporate/v1/create/partner/travel-request')
        self.assertEqual(
            self.config.travel_request_recall_endpoint,
            '/internal/corporate/v1/update/partner/travel-request')

    def test_auth_headers_use_partner_apikey_and_client_code(self):
        headers = self.config._get_auth_headers()
        self.assertEqual(headers['partner-apikey'], 'PARTNER-KEY-1')
        self.assertEqual(headers['client-code'], 'CLIENT-CODE-1')
        self.assertNotIn('clientId', headers)
        self.assertNotIn('apiKey', headers)

    def test_auth_headers_missing_credentials_raises(self):
        # client_code/partner_api_key are required=True (NOT NULL at the DB
        # level), so an incomplete config must be built in-memory with new()
        # rather than by nulling a field on a persisted record.
        incomplete_config = self.env['bxi.mybiz.config'].new({
            'name': 'Incomplete Config',
            'partner_api_key': 'PARTNER-KEY-1',
            'client_code': False,
        })
        with self.assertRaises(UserError):
            incomplete_config._get_auth_headers()

    def test_create_endpoint_is_full_url(self):
        url = self.config._get_endpoint('travel_request_endpoint')
        self.assertEqual(
            url, 'https://mybiz.makemytrip.com/corporate/v1/create/partner/travel-request')

    def test_recall_endpoint_is_full_url(self):
        url = self.config._get_endpoint('travel_request_recall_endpoint')
        self.assertEqual(
            url,
            'https://mybiz.makemytrip.com/internal/corporate/v1/update/partner/travel-request')

    @patch('odoo.addons.bxi_mybiz_integration.models.mybiz_config.requests.head')
    def test_action_test_connection_success(self, mock_head):
        mock_head.return_value = MagicMock(status_code=200)
        result = self.config.action_test_connection()
        self.assertEqual(result['params']['type'], 'success')

    @patch('odoo.addons.bxi_mybiz_integration.models.mybiz_config.requests.head')
    def test_action_test_connection_auth_failure_mentions_new_fields(self, mock_head):
        mock_head.return_value = MagicMock(status_code=403)
        self.config.action_test_connection()
        self.assertIn('Partner API Key', self.config.last_test_status)
