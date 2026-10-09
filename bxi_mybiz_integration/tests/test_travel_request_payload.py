# -*- coding: utf-8 -*-
import calendar
import datetime
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.bxi_mybiz_integration.models.travel_request import _epoch_ms


@tagged('post_install', '-at_install')
class TestEpochMs(TransactionCase):
    """Unit tests for the epoch-millisecond date helper the real API requires."""

    def test_none_returns_none(self):
        self.assertIsNone(_epoch_ms(None))

    def test_date_is_combined_with_midnight(self):
        value = datetime.date(2030, 1, 10)
        expected = int(calendar.timegm(datetime.datetime(2030, 1, 10).timetuple()) * 1000)
        self.assertEqual(_epoch_ms(value), expected)

    def test_datetime_is_converted_directly(self):
        value = datetime.datetime(2030, 1, 10, 14, 30)
        expected = int(calendar.timegm(value.timetuple()) * 1000)
        self.assertEqual(_epoch_ms(value), expected)


@tagged('post_install', '-at_install')
class TestMybizPayload(TransactionCase):
    """Tests for the myBiz payload builder matching the real API contract."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.india = cls.env.ref('base.in')
        cls.manager = cls.env['hr.employee'].create({'name': 'Payload Manager'})
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Payload Employee',
            'parent_id': cls.manager.id,
            'work_email': 'payload.employee@example.com',
        })
        cls.config = cls.env['bxi.mybiz.config'].create({
            'name': 'Payload Config',
            'partner_api_key': 'KEY',
            'client_code': 'CODE',
        })
        cls.request = cls.env['travel.request'].create({
            'employee_id': cls.employee.id,
            'manager_id': cls.manager.id,
            'travel_purpose': 'Quarterly review',
            'from_city': 'Bengaluru',
            'to_city': 'Delhi',
            'from_country': cls.india.id,
            'to_country': cls.india.id,
            'departure_date': '2030-03-01',
            'return_date': '2030-03-05',
            'trip_type': 'round_trip',
            'travel_class': 'business',
        })
        cls.flight_option = cls.env['travel.request.option'].create({
            'travel_request_id': cls.request.id,
            'option_type': 'flight',
            'origin_code': 'BLR',
            'destination_code': 'DEL',
            'departure_datetime': '2030-03-01 06:00:00',
            'arrival_datetime': '2030-03-01 08:30:00',
            'origin_country_id': cls.india.id,
            'destination_country_id': cls.india.id,
        })
        cls.hotel_option = cls.env['travel.request.option'].create({
            'travel_request_id': cls.request.id,
            'option_type': 'hotel',
            'hotel_city': 'Delhi',
            'checkin_date': '2030-03-01',
            'checkout_date': '2030-03-05',
            'rooms': 2,
        })

    def test_payload_top_level_shape(self):
        payload = self.request._build_mybiz_payload()
        self.assertEqual(set(payload.keys()), {
            'deviceDetails', 'travellerDetails', 'services',
            'reasonForTravel', 'approvalDetails', 'trfId',
        })
        self.assertEqual(payload['trfId'], self.request.name)
        self.assertEqual(payload['reasonForTravel'], {'reason': 'Quarterly review'})

    def test_traveller_details_uses_pax_details_list(self):
        payload = self.request._build_mybiz_payload()
        pax_details = payload['travellerDetails']['paxDetails']
        self.assertEqual(len(pax_details), 1)
        self.assertEqual(pax_details[0]['name'], self.employee.name)
        self.assertTrue(pax_details[0]['isPrimaryPax'])

    def test_flight_service_has_journey_details(self):
        payload = self.request._build_mybiz_payload()
        flights = payload['services']['FLIGHT']
        self.assertEqual(len(flights), 1)
        flight = flights[0]
        self.assertEqual(flight['tripType'], 'ROUND_TRIP')
        self.assertEqual(flight['travelClass'], 'BUSINESS')
        self.assertTrue(flight['serviceId'])
        journey = flight['journeyDetails'][0]
        self.assertEqual(journey['from']['airportCode'], 'BLR')
        self.assertEqual(journey['from']['countryCode'], self.india.code)
        self.assertEqual(journey['to']['airportCode'], 'DEL')
        self.assertIsInstance(journey['departureDate'], int)

    def test_hotel_service_has_room_details_per_room(self):
        payload = self.request._build_mybiz_payload()
        hotels = payload['services']['HOTEL']
        self.assertEqual(len(hotels), 1)
        hotel = hotels[0]
        self.assertTrue(hotel['serviceId'])
        self.assertEqual(len(hotel['roomDetailsPaxWise']), 2)
        self.assertIsInstance(hotel['checkin'], int)
        self.assertIsInstance(hotel['checkout'], int)

    def test_service_id_is_stable_across_builds(self):
        first = self.request._build_mybiz_payload()
        second = self.request._build_mybiz_payload()
        self.assertEqual(
            first['services']['FLIGHT'][0]['serviceId'],
            second['services']['FLIGHT'][0]['serviceId'],
        )

    def test_approver_details_deduplicates_same_person(self):
        self.request.hr_approved_by = self.manager  # same as manager_id
        payload = self.request._build_mybiz_payload()
        approvers = payload['approvalDetails']['approverDetails']
        self.assertEqual(len(approvers), 1)
        self.assertEqual(approvers[0]['approvalLevel'], 1)

    def test_approver_details_include_manager_and_distinct_hr(self):
        hr_person = self.env['hr.employee'].create({'name': 'Payload HR Approver'})
        self.request.hr_approved_by = hr_person
        payload = self.request._build_mybiz_payload()
        approvers = payload['approvalDetails']['approverDetails']
        self.assertEqual(len(approvers), 2)
        self.assertEqual(approvers[1]['approvalLevel'], 2)
        self.assertEqual(approvers[1]['name'], hr_person.name)

    @patch('odoo.addons.bxi_mybiz_integration.models.travel_request.requests.post')
    def test_push_to_mybiz_success_stores_response_fields(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            'travelRequestUrl': 'https://mybiz.example.com/trf/123',
            'status': 'success',
            'statusCode': 200,
            'responseCode': '600',
            'message': 'Operation executed successfully.',
        }
        mock_post.return_value = mock_response

        self.request._push_to_mybiz()

        self.assertEqual(self.request.mybiz_status, 'pending')
        self.assertEqual(
            self.request.mybiz_travel_request_url, 'https://mybiz.example.com/trf/123')
        self.assertEqual(self.request.mybiz_response_code, '600')
        self.assertFalse(self.request.mybiz_error)

        called_headers = mock_post.call_args.kwargs['headers']
        self.assertEqual(called_headers['partner-apikey'], 'KEY')
        self.assertEqual(called_headers['client-code'], 'CODE')

    @patch('odoo.addons.bxi_mybiz_integration.models.travel_request.requests.post')
    def test_push_to_mybiz_non_success_status_marks_failed(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            'status': 'failure',
            'message': 'Invalid pax details.',
        }
        mock_post.return_value = mock_response

        self.request._push_to_mybiz()

        self.assertEqual(self.request.mybiz_status, 'failed')
        self.assertEqual(self.request.mybiz_error, 'Invalid pax details.')

    def test_sync_mybiz_status_is_disabled(self):
        self.request.mybiz_service_id = 'SVC-1'
        # Should be a no-op and must not raise, since myBiz publishes no status endpoint.
        self.request._sync_mybiz_status()
        self.assertEqual(self.request.mybiz_service_id, 'SVC-1')


@tagged('post_install', '-at_install')
class TestMybizPushWithoutServices(TransactionCase):
    """myBiz only books flights and hotels; other trips must not be pushed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.india = cls.env.ref('base.in')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Bus Traveller',
            'work_email': 'bus.traveller@example.com',
        })
        cls.env['bxi.mybiz.config'].create({
            'name': 'No Services Config',
            'partner_api_key': 'KEY',
            'client_code': 'CODE',
        })

    def _bus_request(self, **overrides):
        vals = {
            'employee_id': self.employee.id,
            'travel_purpose': 'Meeting with OEM',
            'from_city': 'Jaipur',
            'to_city': 'Noida',
            'from_country': self.india.id,
            'to_country': self.india.id,
            'departure_date': '2030-10-01',
            'return_date': '2030-10-01',
            'mode_of_travel': 'bus',
            'state': 'mybiz_pending',
        }
        vals.update(overrides)
        return self.env['travel.request'].create(vals)

    @patch('odoo.addons.bxi_mybiz_integration.models.travel_request.requests.post')
    def test_bus_only_request_is_approved_without_calling_mybiz(self, mock_post):
        request = self._bus_request()
        self.env['travel.request.option'].create({
            'travel_request_id': request.id,
            'option_type': 'bus',
        })

        request._push_to_mybiz()

        mock_post.assert_not_called()
        self.assertEqual(request.state, 'approved')
        self.assertEqual(request.mybiz_status, 'not_pushed')
        self.assertTrue(any(
            'Not sent to MakeMyTrip myBiz' in (msg.body or '') for msg in request.message_ids))

    @patch('odoo.addons.bxi_mybiz_integration.models.travel_request.requests.post')
    def test_retry_of_failed_bus_request_approves_it(self, mock_post):
        request = self._bus_request(
            mybiz_status='failed', mybiz_error='No serivces present in request')

        request.action_retry_mybiz_push()

        mock_post.assert_not_called()
        self.assertEqual(request.state, 'approved')
        self.assertEqual(request.mybiz_status, 'not_pushed')
        self.assertFalse(request.mybiz_error)

    @patch('odoo.addons.bxi_mybiz_integration.models.travel_request.requests.post')
    def test_bus_request_with_hotel_is_still_pushed(self, mock_post):
        mock_post.return_value.raise_for_status.return_value = None
        mock_post.return_value.json.return_value = {'status': 'success'}
        request = self._bus_request(
            hotel_required=True,
            hotel_city='Noida',
            hotel_checkin='2030-10-01',
            hotel_checkout='2030-10-02',
        )

        request._push_to_mybiz()

        mock_post.assert_called_once()
        services = mock_post.call_args.kwargs['json']['services']
        self.assertEqual(list(services), ['HOTEL'])
        self.assertEqual(request.state, 'mybiz_pending')
        self.assertEqual(request.mybiz_status, 'pending')


@tagged('post_install', '-at_install')
class TestMybizPushPastDates(TransactionCase):
    """myBiz rejects any date that is not after the current time."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.india = cls.env.ref('base.in')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Date Traveller',
            'work_email': 'date.traveller@example.com',
        })
        cls.env['bxi.mybiz.config'].create({
            'name': 'Past Dates Config',
            'partner_api_key': 'KEY',
            'client_code': 'CODE',
        })
        cls.today = fields.Date.today()
        cls.past = cls.today - datetime.timedelta(days=30)
        cls.future = cls.today + datetime.timedelta(days=30)

    def _flight_request(self, departure, **overrides):
        vals = {
            'employee_id': self.employee.id,
            'travel_purpose': 'Meeting with OEM',
            'from_city': 'Jaipur',
            'to_city': 'Delhi',
            'from_country': self.india.id,
            'to_country': self.india.id,
            'departure_date': departure,
            'return_date': departure,
            'mode_of_travel': 'flight',
            'state': 'mybiz_pending',
        }
        vals.update(overrides)
        return self.env['travel.request'].create(vals)

    @patch('odoo.addons.bxi_mybiz_integration.models.travel_request.requests.post')
    def test_past_flight_date_is_not_pushed(self, mock_post):
        request = self._flight_request(self.past)

        request._push_to_mybiz()

        mock_post.assert_not_called()
        self.assertEqual(request.state, 'mybiz_pending')
        self.assertEqual(request.mybiz_status, 'failed')
        self.assertIn(
            f'flight departure {self.past.strftime("%d %b %Y")}', request.mybiz_error)

    @patch('odoo.addons.bxi_mybiz_integration.models.travel_request.requests.post')
    def test_trip_dated_today_is_not_pushed(self, mock_post):
        # Date-only values go out as midnight UTC, which has already passed.
        request = self._flight_request(self.today)

        request._push_to_mybiz()

        mock_post.assert_not_called()
        self.assertEqual(request.mybiz_status, 'failed')

    @patch('odoo.addons.bxi_mybiz_integration.models.travel_request.requests.post')
    def test_past_hotel_checkin_blocks_push_with_future_flight(self, mock_post):
        request = self._flight_request(
            self.future,
            return_date=self.future + datetime.timedelta(days=2),
            hotel_required=True,
            hotel_city='Delhi',
            hotel_checkin=self.past,
            hotel_checkout=self.future,
        )

        request._push_to_mybiz()

        mock_post.assert_not_called()
        self.assertIn('hotel check-in', request.mybiz_error)
        self.assertNotIn('flight', request.mybiz_error)

    @patch('odoo.addons.bxi_mybiz_integration.models.travel_request.requests.post')
    def test_future_dates_are_pushed(self, mock_post):
        mock_post.return_value.raise_for_status.return_value = None
        mock_post.return_value.json.return_value = {'status': 'success'}
        request = self._flight_request(self.future)

        request._push_to_mybiz()

        mock_post.assert_called_once()
        self.assertEqual(request.mybiz_status, 'pending')
