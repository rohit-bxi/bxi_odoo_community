# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMybizConfig(TransactionCase):
    """Tests for bxi.mybiz.config — credential storage and endpoint helpers.

    bxi_mybiz_integration (when installed alongside this module, as in a
    normal deployment) overrides the auth-header contract, the default
    create/recall endpoint paths, and adds required partner_api_key/
    client_code fields. These tests detect whether that override is active
    and assert against whichever contract is actually in effect, instead of
    assuming this module is ever installed in isolation.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.has_override = 'partner_api_key' in cls.env['bxi.mybiz.config']._fields

        vals = {
            'name': 'Primary Config',
            'client_id': 'CLIENT1',
            'org_id': 'ORG1',
            'api_key': 'SECRET1',
            'base_url': 'https://mybiz.example.com/api/v1',
            'travel_request_endpoint': '/travelRequest/create',
        }
        if cls.has_override:
            vals.update({'partner_api_key': 'PARTNER1', 'client_code': 'CODE1'})
        cls.config = cls.env['bxi.mybiz.config'].create(vals)

    def test_get_active_config_returns_active_record(self):
        found = self.env['bxi.mybiz.config'].get_active_config(self.env.company.id)
        self.assertEqual(found, self.config)

    def test_get_active_config_ignores_inactive(self):
        self.config.active = False
        found = self.env['bxi.mybiz.config'].get_active_config(self.env.company.id)
        self.assertFalse(found)

    def test_get_auth_headers_returns_expected_keys(self):
        headers = self.config._get_auth_headers()
        if self.has_override:
            self.assertEqual(headers['partner-apikey'], 'PARTNER1')
            self.assertEqual(headers['client-code'], 'CODE1')
        else:
            self.assertEqual(headers['clientId'], 'CLIENT1')
            self.assertEqual(headers['orgId'], 'ORG1')
            self.assertEqual(headers['apiKey'], 'SECRET1')

    def test_get_auth_headers_missing_credentials_raises(self):
        # The required credential fields are required=True (NOT NULL at the
        # DB level), so an incomplete config must be built in-memory with
        # new() rather than by nulling a field on a persisted record.
        if self.has_override:
            incomplete_vals = {
                'name': 'Incomplete Config',
                'partner_api_key': 'PARTNER1',
                'client_code': False,
            }
        else:
            incomplete_vals = {
                'name': 'Incomplete Config',
                'client_id': 'CLIENT1',
                'org_id': 'ORG1',
                'api_key': False,
            }
        incomplete_config = self.env['bxi.mybiz.config'].new(incomplete_vals)
        with self.assertRaises(UserError):
            incomplete_config._get_auth_headers()

    def test_get_endpoint_builds_full_url(self):
        url = self.config._get_endpoint('travel_request_endpoint')
        self.assertEqual(
            url, 'https://mybiz.example.com/api/v1/travelRequest/create')

    def test_get_endpoint_normalizes_missing_leading_slash(self):
        self.config.travel_request_endpoint = 'travelRequest/create'
        url = self.config._get_endpoint('travel_request_endpoint')
        self.assertEqual(
            url, 'https://mybiz.example.com/api/v1/travelRequest/create')

    @patch('requests.head')
    def test_action_test_connection_success(self, mock_head):
        mock_head.return_value = MagicMock(status_code=200)
        result = self.config.action_test_connection()
        self.assertIn('successful', self.config.last_test_status)
        self.assertEqual(result['params']['type'], 'success')

    @patch('requests.head')
    def test_action_test_connection_auth_failure(self, mock_head):
        mock_head.return_value = MagicMock(status_code=401)
        self.config.action_test_connection()
        self.assertIn('Authentication failed', self.config.last_test_status)

    @patch('requests.head')
    def test_action_test_connection_connection_error(self, mock_head):
        import requests as requests_lib
        mock_head.side_effect = requests_lib.exceptions.ConnectionError()
        self.config.action_test_connection()
        self.assertIn('Connection refused', self.config.last_test_status)
