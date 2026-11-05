# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.bxi_glpi_asset_sync.models import glpi_client
from odoo.addons.bxi_glpi_asset_sync.models.glpi_client import GlpiClient, GlpiError


def response(status=200, json=None, headers=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json
    resp.content = b'x' if json is not None else b''
    resp.text = ''
    resp.headers = headers or {}
    return resp


@tagged('post_install', '-at_install')
class TestGlpiClient(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['glpi.config'].create({
            'name': 'Client test',
            'base_url': 'https://glpi.test/',
            'client_id': 'cid',
            'client_secret': 'secret',
            'username': 'odoo',
            'password': 'pwd',
            'page_size': 2,
        })

    def setUp(self):
        super().setUp()
        glpi_client._token_cache.clear()
        self.client = GlpiClient(self.config.sudo())
        self.client.session = MagicMock()
        self.client.session.post.return_value = response(json={'access_token': 'tok1', 'expires_in': 3600})

    def test_token_request(self):
        self.client.session.request.return_value = response(json=[])
        self.client.list_assets('Computer')
        url = self.client.session.post.call_args.args[0]
        data = self.client.session.post.call_args.kwargs['data']
        self.assertEqual(url, 'https://glpi.test/api.php/token')
        self.assertEqual(data['grant_type'], 'password')
        self.assertEqual(data['scope'], 'api')
        headers = self.client.session.request.call_args.kwargs['headers']
        self.assertEqual(headers['Authorization'], 'Bearer tok1')

    def test_paging(self):
        self.client.session.request.side_effect = [
            response(json=[{'id': 1}, {'id': 2}], headers={'Content-Range': '0-1/3'}),
            response(json=[{'id': 3}], headers={'Content-Range': '2-2/3'}),
        ]
        items = self.client.list_assets('Computer')
        self.assertEqual([i['id'] for i in items], [1, 2, 3])
        starts = [c.kwargs['params']['start'] for c in self.client.session.request.call_args_list]
        self.assertEqual(starts, [0, 2])
        self.assertTrue(self.client.session.request.call_args.args[1].startswith(
            'https://glpi.test/api.php/v2/Assets/Computer'))

    def test_refreshes_token_once_on_401(self):
        self.client.session.post.side_effect = [
            response(json={'access_token': 'old', 'expires_in': 3600}),
            response(json={'access_token': 'new', 'expires_in': 3600}),
        ]
        self.client.session.request.side_effect = [response(status=401, json={}), response(json=[])]
        self.client.list_assets('Computer')
        headers = self.client.session.request.call_args.kwargs['headers']
        self.assertEqual(headers['Authorization'], 'Bearer new')

    def test_auth_failure_raises(self):
        self.client.session.post.return_value = response(
            status=400, json={'error_description': 'Check the `client_id` parameter'})
        with self.assertRaisesRegex(GlpiError, 'client_id'):
            self.client.list_assets('Computer')

    def test_404_allowed(self):
        self.client.session.request.return_value = response(status=404, json={})
        self.assertIsNone(self.client.get_infocom('Computer', 9))

    @patch.object(glpi_client.time, 'sleep')
    def test_retries_server_errors(self, sleep):
        self.client.session.request.side_effect = [
            response(status=502, json={}), response(json={'id': 5, 'value': 10})]
        self.assertEqual(self.client.get_infocom('Computer', 5)['id'], 5)
        sleep.assert_called_once()
