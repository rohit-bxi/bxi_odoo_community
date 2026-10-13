# -*- coding: utf-8 -*-
import datetime
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMybizCodes(TransactionCase):
    """Flight airport codes and hotel city codes come from MakeMyTrip's code lists."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.india = cls.env.ref('base.in')
        cls.maharashtra = cls.env.ref('base.state_in_mh')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Codes Traveller',
            'work_email': 'codes.traveller@example.com',
        })
        cls.env['bxi.mybiz.config'].create({
            'name': 'Codes Config',
            'partner_api_key': 'KEY',
            'client_code': 'CODE',
        })
        cls.future = fields.Date.today() + datetime.timedelta(days=30)
        cls.City = cls.env['bxi.mybiz.city']
        # Two same-named cities, told apart by state.
        cls.testpur_bihar, cls.testpur_mh = cls.City.create([{
            'code': 'CTTESTB', 'name': 'Testpur', 'state_name': 'Bihar',
            'country_code': 'IN', 'country_name': 'India',
        }, {
            'code': 'CTTESTM', 'name': 'Testpur', 'state_name': 'Maharashtra',
            'country_code': 'IN', 'country_name': 'India',
        }])

    def _request(self, **overrides):
        vals = {
            'employee_id': self.employee.id,
            'travel_purpose': 'Plant visit',
            'from_city': 'Jaipur',
            'to_city': 'Delhi',
            'from_country': self.india.id,
            'to_country': self.india.id,
            'departure_date': self.future,
            'return_date': self.future + datetime.timedelta(days=1),
            'mode_of_travel': 'flight',
            'trip_type': 'one_way',
            'state': 'mybiz_pending',
        }
        vals.update(overrides)
        return self.env['travel.request'].create(vals)

    def _flight(self, request, origin, destination):
        return self.env['travel.request.option'].create({
            'travel_request_id': request.id,
            'option_type': 'flight',
            'origin_code': origin,
            'destination_code': destination,
            'departure_datetime': datetime.datetime.combine(self.future, datetime.time(9, 0)),
        })

    def _hotel(self, request, city, **overrides):
        vals = {
            'travel_request_id': request.id,
            'option_type': 'hotel',
            'hotel_city': city,
            'checkin_date': self.future,
            'checkout_date': self.future + datetime.timedelta(days=1),
        }
        vals.update(overrides)
        return self.env['travel.request.option'].create(vals)

    # ── Code lists loaded from MakeMyTrip's workbook ─────────────────

    def test_code_lists_are_loaded(self):
        airport = self.env['bxi.mybiz.airport'].search([('code', '=', 'DEL')])
        self.assertEqual(airport.city, 'New Delhi')
        # Jaipur is only in the India sheet, not in the worldwide dump.
        jaipur = self.City.search([('code', '=', 'CTJAI')])
        self.assertEqual((jaipur.name, jaipur.country_code), ('Jaipur', 'IN'))

    # ── Flights ──────────────────────────────────────────────────────

    def test_flight_city_names_come_from_airport_list(self):
        request = self._request()
        self._flight(request, 'JAI', 'DEL')

        leg = request._build_mybiz_payload()['services']['FLIGHT'][0]['journeyDetails'][0]

        self.assertEqual(leg['from']['cityName'], 'Jaipur')
        self.assertEqual(leg['to']['cityName'], 'New Delhi')

    @patch('odoo.addons.bxi_mybiz_integration.models.travel_request.requests.post')
    def test_airport_code_missing_from_list_is_not_pushed(self, mock_post):
        request = self._request()
        self._flight(request, 'JAI', 'XYZ')

        request._push_to_mybiz()

        mock_post.assert_not_called()
        self.assertIn("'JAI' → 'XYZ'", request.mybiz_error)

    # ── Hotels ───────────────────────────────────────────────────────

    def test_hotel_city_name_is_sent_as_mybiz_city_code(self):
        request = self._request(mode_of_travel='bus')
        hotel = self._hotel(request, 'noida')

        sent = request._build_mybiz_payload()['services']['HOTEL'][0]

        self.assertEqual(
            (sent['cityCode'], sent['cityName'], sent['countryCode']), ('CTNOI', 'Noida', 'IN'))
        self.assertEqual(hotel.mybiz_city_id.code, 'CTNOI')

    def test_picked_mybiz_city_wins_over_hotel_city_name(self):
        request = self._request(mode_of_travel='bus')
        self._hotel(request, 'Noida', mybiz_city_id=self.testpur_bihar.id)

        sent = request._build_mybiz_payload()['services']['HOTEL'][0]

        self.assertEqual(sent['cityCode'], 'CTTESTB')

    def test_same_named_cities_are_told_apart_by_state(self):
        request = self._request(mode_of_travel='bus', to_state=self.maharashtra.id)
        self._hotel(request, 'Testpur')

        sent = request._build_mybiz_payload()['services']['HOTEL'][0]

        self.assertEqual(sent['cityCode'], 'CTTESTM')

    @patch('odoo.addons.bxi_mybiz_integration.models.travel_request.requests.post')
    def test_ambiguous_hotel_city_is_not_pushed(self, mock_post):
        request = self._request(mode_of_travel='bus')
        hotel = self._hotel(request, 'Testpur')

        request._push_to_mybiz()

        mock_post.assert_not_called()
        self.assertFalse(hotel.mybiz_city_id)
        self.assertIn("MakeMyTrip City", request.mybiz_error)
        self.assertIn("'Testpur'", request.mybiz_error)

    @patch('odoo.addons.bxi_mybiz_integration.models.travel_request.requests.post')
    def test_unknown_hotel_city_is_not_pushed(self, mock_post):
        request = self._request(mode_of_travel='bus')
        self._hotel(request, 'Atlantis')

        request._push_to_mybiz()

        mock_post.assert_not_called()
        self.assertEqual(request.mybiz_status, 'failed')
        self.assertIn("'Atlantis'", request.mybiz_error)
