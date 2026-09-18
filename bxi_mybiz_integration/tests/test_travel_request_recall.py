# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMybizRecall(TransactionCase):
    """Tests for the myBiz Recall Travel Request API integration."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({'name': 'Recall Tester'})
        cls.config = cls.env['bxi.mybiz.config'].create({
            'name': 'Recall Config',
            'partner_api_key': 'KEY',
            'client_code': 'CODE',
        })
        cls.request = cls.env['travel.request'].create({
            'employee_id': cls.employee.id,
            'travel_purpose': 'Recall testing',
            'from_city': 'Pune',
            'to_city': 'Chennai',
            'departure_date': '2030-04-01',
        })
        cls.option = cls.env['travel.request.option'].create({
            'travel_request_id': cls.request.id,
            'option_type': 'flight',
            'origin_code': 'PNQ',
            'destination_code': 'MAA',
            'mybiz_ref': 'SVC-ABC',
            'mybiz_status': 'confirmed',
        })

    def test_recall_without_service_id_raises(self):
        unpushed = self.env['travel.request.option'].create({
            'travel_request_id': self.request.id,
            'option_type': 'hotel',
        })
        with self.assertRaises(UserError):
            unpushed._recall_mybiz_service()

    def test_recall_already_cancelled_raises(self):
        self.option.mybiz_status = 'cancelled'
        with self.assertRaises(UserError):
            self.option._recall_mybiz_service()

    @patch('odoo.addons.bxi_mybiz_integration.models.travel_request_option.requests.post')
    def test_recall_success_marks_option_cancelled(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            'status': 'success', 'statusCode': 200,
            'responseCode': '600', 'message': 'Operation executed successfully.',
        }
        mock_post.return_value = mock_response

        self.option._recall_mybiz_service()

        self.assertEqual(self.option.mybiz_status, 'cancelled')
        sent_payload = mock_post.call_args.kwargs['json']
        self.assertEqual(sent_payload, {
            'trfId': self.request.name,
            'action': 'recalled',
            'serviceId': 'SVC-ABC',
        })

    @patch('odoo.addons.bxi_mybiz_integration.models.travel_request_option.requests.post')
    def test_recall_failure_response_raises(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {'status': 'failure', 'message': 'Unknown serviceId'}
        mock_post.return_value = mock_response

        with self.assertRaises(UserError):
            self.option._recall_mybiz_service()
        # Status must remain unchanged on failure.
        self.assertEqual(self.option.mybiz_status, 'confirmed')

    def test_recall_all_without_pushed_services_raises(self):
        fresh_request = self.env['travel.request'].create({
            'employee_id': self.employee.id,
            'travel_purpose': 'No services pushed',
            'from_city': 'Kochi',
            'to_city': 'Goa',
            'departure_date': '2030-05-01',
        })
        with self.assertRaises(UserError):
            fresh_request.action_recall_all_mybiz_services()

    @patch('odoo.addons.bxi_mybiz_integration.models.travel_request_option.requests.post')
    def test_recall_all_cancels_request_when_all_services_recalled(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {'status': 'success', 'message': 'OK'}
        mock_post.return_value = mock_response

        self.request.state = 'mybiz_pending'
        self.request.action_recall_all_mybiz_services()

        self.assertEqual(self.option.mybiz_status, 'cancelled')
        self.assertEqual(self.request.mybiz_status, 'cancelled')
        self.assertEqual(self.request.state, 'cancelled')

    def test_ensure_service_id_is_idempotent(self):
        option = self.env['travel.request.option'].create({
            'travel_request_id': self.request.id,
            'option_type': 'hotel',
        })
        option._ensure_mybiz_service_id()
        first_ref = option.mybiz_ref
        self.assertTrue(first_ref)
        option._ensure_mybiz_service_id()
        self.assertEqual(option.mybiz_ref, first_ref)
