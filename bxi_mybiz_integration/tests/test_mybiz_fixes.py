# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

import requests

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.bxi_mybiz_integration.models.mmt_codes import (
    resolve_airport_code, resolve_city_code,
)

PUSH_POST = 'odoo.addons.bxi_mybiz_integration.models.travel_request.requests.post'
RECALL_POST = 'odoo.addons.bxi_mybiz_integration.models.travel_request_option.requests.post'


def _ok(data):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = data
    return resp


def _http_error(status, text):
    resp = requests.Response()
    resp.status_code = status
    resp._content = text.encode()
    err = requests.exceptions.HTTPError(f'{status} Client Error', response=resp)
    mock = MagicMock()
    mock.raise_for_status.side_effect = err
    return mock


@tagged('post_install', '-at_install')
class TestMmtCodes(TransactionCase):

    def test_airport_from_city_names_and_aliases(self):
        self.assertEqual(resolve_airport_code('Udaipur', 'India'), 'UDR')
        self.assertEqual(resolve_airport_code('Delhi', 'India'), 'DEL')
        self.assertEqual(resolve_airport_code('bangalore', 'India'), 'BLR')
        self.assertEqual(resolve_airport_code('Mumbai', 'India'), 'BOM')

    def test_airport_for_cities_without_one(self):
        self.assertEqual(resolve_airport_code('Noida', 'India'), 'DEL')
        self.assertEqual(resolve_airport_code('Gurgaon', 'India'), 'DEL')
        self.assertEqual(resolve_airport_code('Gandhinagar', 'India'), 'AMD')
        self.assertEqual(resolve_airport_code('Thoothukudi', 'India'), 'TCR')
        self.assertEqual(resolve_airport_code('Aero city, New delhi', 'India'), 'DEL')
        # Typos are not guessed; the user is asked for the code.
        self.assertIsNone(resolve_airport_code('Chennnai', 'India'))

    def test_airport_prefers_international_airport(self):
        self.assertEqual(resolve_airport_code('Hyderabad', 'India'), 'HYD')

    def test_airport_explicit_code_kept(self):
        self.assertEqual(resolve_airport_code('BLR'), 'BLR')
        self.assertEqual(resolve_airport_code('del'), 'DEL')

    def test_airport_unknown_returns_none(self):
        self.assertIsNone(resolve_airport_code('Nowhereville'))
        self.assertIsNone(resolve_airport_code(''))

    def test_hotel_city_code(self):
        self.assertEqual(resolve_city_code('Delhi', 'India'), ('CTDEL', 'Delhi'))
        self.assertEqual(resolve_city_code('New Delhi', 'India')[0], 'CTDEL')
        self.assertEqual(resolve_city_code('Goa', 'India')[0], 'CTGOI')
        self.assertEqual(resolve_city_code('CTBOM'), ('CTBOM', 'Mumbai'))
        self.assertIsNone(resolve_city_code('Nowhereville'))


class _MybizRequestCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.india = cls.env.ref('base.in')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Fix Traveller', 'work_email': 'fix.traveller@example.com'})
        cls.env['bxi.mybiz.config'].create({
            'name': 'Fix Config', 'partner_api_key': 'KEY', 'client_code': 'CODE'})

    def _request(self, **vals):
        base = {
            'employee_id': self.employee.id,
            'travel_purpose': 'Site visit',
            'from_city': 'Ghaziabad',
            'to_city': 'Udaipur',
            'from_country': self.india.id,
            'to_country': self.india.id,
            'departure_date': '2030-06-01',
            'return_date': '2030-06-03',
            'trip_type': 'one_way',
            'mode_of_travel': 'flight',
            'state': 'mybiz_pending',
        }
        base.update(vals)
        return self.env['travel.request'].create(base)


@tagged('post_install', '-at_install')
class TestMybizPushFixes(_MybizRequestCase):

    @patch(PUSH_POST)
    def test_city_names_are_sent_as_iata_codes(self, mock_post):
        mock_post.return_value = _ok({'status': 'success'})
        request = self._request()
        request._push_to_mybiz()
        flight = mock_post.call_args.kwargs['json']['services']['FLIGHT'][0]
        self.assertEqual(flight['tripType'], 'ONWARDS')
        self.assertEqual(len(flight['journeyDetails']), 1)
        self.assertEqual(flight['journeyDetails'][0]['from']['airportCode'], 'VDX')
        self.assertEqual(flight['journeyDetails'][0]['to']['airportCode'], 'UDR')

    @patch(PUSH_POST)
    def test_auto_generated_round_trip_includes_return_leg(self, mock_post):
        mock_post.return_value = _ok({'status': 'success'})
        request = self._request(from_city='Pune', to_city='Chennai', trip_type='round_trip')
        request._push_to_mybiz()
        flight = mock_post.call_args.kwargs['json']['services']['FLIGHT'][0]
        self.assertEqual(flight['tripType'], 'ROUND_TRIP')
        legs = [(j['from']['airportCode'], j['to']['airportCode'])
                for j in flight['journeyDetails']]
        self.assertEqual(legs, [('PNQ', 'MAA'), ('MAA', 'PNQ')])

    @patch(PUSH_POST)
    def test_several_flight_segments_are_each_onwards(self, mock_post):
        mock_post.return_value = _ok({'status': 'success'})
        request = self._request(trip_type='round_trip')
        Option = self.env['travel.request.option']
        for origin, dest in (('BLR', 'DEL'), ('DEL', 'BLR')):
            Option.create({'travel_request_id': request.id, 'option_type': 'flight',
                           'origin_code': origin, 'destination_code': dest})
        request._push_to_mybiz()
        flights = mock_post.call_args.kwargs['json']['services']['FLIGHT']
        self.assertEqual([f['tripType'] for f in flights], ['ONWARDS', 'ONWARDS'])

    @patch(PUSH_POST)
    def test_unknown_airport_blocks_push(self, mock_post):
        request = self._request(from_city='Nowhereville')
        request._push_to_mybiz()
        mock_post.assert_not_called()
        self.assertEqual(request.mybiz_status, 'failed')
        self.assertIn('Nowhereville', request.mybiz_error)
        self.assertEqual(request.state, 'mybiz_pending')
        self.assertEqual(request.travel_option_ids.mybiz_status, 'failed')
        self.assertTrue(any('myBiz Push Failed' in (m.body or '') for m in request.message_ids))

    @patch(PUSH_POST)
    def test_missing_email_blocks_push(self, mock_post):
        employee = self.env['hr.employee'].create({'name': 'No Mail'})
        request = self._request(employee_id=employee.id)
        request._push_to_mybiz()
        mock_post.assert_not_called()
        self.assertIn('email', request.mybiz_error)

    @patch(PUSH_POST)
    def test_http_error_keeps_raw_response(self, mock_post):
        mock_post.return_value = _http_error(400, '{"message": "Requisition Id empty"}')
        request = self._request()
        request._push_to_mybiz()
        self.assertEqual(request.mybiz_status, 'failed')
        self.assertIn('HTTP 400', request.mybiz_error)
        self.assertIn('Requisition Id empty', request.mybiz_raw_response)
        self.assertEqual(request.travel_option_ids.mybiz_status, 'failed')

    @patch(PUSH_POST)
    def test_timeout_is_posted_in_chatter(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout()
        request = self._request()
        request._push_to_mybiz()
        self.assertEqual(request.mybiz_status, 'failed')
        self.assertTrue(any('timed out' in (m.body or '') for m in request.message_ids))

    @patch(PUSH_POST)
    def test_failed_push_segment_cannot_be_recalled(self, mock_post):
        mock_post.return_value = _ok({'status': 'failure', 'message': 'Bad'})
        request = self._request()
        request._push_to_mybiz()
        option = request.travel_option_ids
        self.assertTrue(option.mybiz_ref)
        with self.assertRaises(UserError):
            option._recall_mybiz_service()
        with self.assertRaises(UserError):
            request.action_recall_all_mybiz_services()


@tagged('post_install', '-at_install')
class TestMybizRecallFixes(_MybizRequestCase):

    def _pushed_request(self, n=2):
        request = self._request(state='approved', mybiz_status='pending')
        options = self.env['travel.request.option'].create([{
            'travel_request_id': request.id,
            'option_type': 'flight',
            'origin_code': 'BLR',
            'destination_code': 'DEL',
            'mybiz_ref': f'SVC-{i}',
            'mybiz_status': 'confirmed',
        } for i in range(n)])
        return request, options

    @patch(RECALL_POST)
    def test_recall_all_keeps_successes_when_one_fails(self, mock_post):
        request, options = self._pushed_request()
        mock_post.side_effect = [
            _ok({'status': 'success', 'message': 'OK'}),
            _ok({'status': 'failure', 'message': 'Unknown serviceId'}),
        ]
        result = request.action_recall_all_mybiz_services()
        self.assertEqual(options.mapped('mybiz_status'), ['cancelled', 'confirmed'])
        self.assertEqual(result['params']['type'], 'warning')
        self.assertIn('Unknown serviceId', result['params']['message'])
        self.assertEqual(request.state, 'approved')

    @patch(RECALL_POST)
    def test_recalling_last_segment_cancels_request(self, mock_post):
        request, options = self._pushed_request()
        mock_post.return_value = _ok({'status': 'success', 'message': 'OK'})
        options[0].action_recall_service()
        self.assertEqual(request.state, 'approved')
        options[1].action_recall_service()
        self.assertEqual(request.mybiz_status, 'cancelled')
        self.assertEqual(request.state, 'cancelled')

    @patch(RECALL_POST)
    def test_akamai_403_explains_whitelist(self, mock_post):
        _request, options = self._pushed_request(n=1)
        mock_post.return_value = _http_error(
            403, '<HTML><HEAD><TITLE>Access Denied</TITLE></HEAD></HTML>')
        with self.assertRaisesRegex(UserError, 'whitelist'):
            options._recall_mybiz_service()
        self.assertEqual(options.mybiz_status, 'confirmed')
