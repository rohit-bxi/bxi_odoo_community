# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestTravelRequestOption(TransactionCase):
    """Tests for travel.request.option — the per-segment (flight/hotel/cab) lines."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({'name': 'Segment Tester'})
        cls.request = cls.env['travel.request'].create({
            'employee_id': cls.employee.id,
            'travel_purpose': 'Segment testing',
            'from_city': 'Delhi',
            'to_city': 'Mumbai',
            'departure_date': '2030-02-01',
        })

    def test_hotel_nights_computed(self):
        option = self.env['travel.request.option'].create({
            'travel_request_id': self.request.id,
            'option_type': 'hotel',
            'checkin_date': '2030-02-01',
            'checkout_date': '2030-02-04',
        })
        self.assertEqual(option.hotel_nights, 3)

    def test_hotel_nights_zero_when_dates_invalid(self):
        option = self.env['travel.request.option'].create({
            'travel_request_id': self.request.id,
            'option_type': 'hotel',
            'checkin_date': '2030-02-04',
            'checkout_date': '2030-02-01',
        })
        self.assertEqual(option.hotel_nights, 0)

    def test_hotel_nights_zero_without_dates(self):
        option = self.env['travel.request.option'].create({
            'travel_request_id': self.request.id,
            'option_type': 'flight',
        })
        self.assertEqual(option.hotel_nights, 0)

    def test_option_count_on_request(self):
        self.env['travel.request.option'].create({
            'travel_request_id': self.request.id,
            'option_type': 'flight',
        })
        self.env['travel.request.option'].create({
            'travel_request_id': self.request.id,
            'option_type': 'cab',
        })
        self.assertEqual(self.request.option_count, 2)

    def test_deleting_request_cascades_to_options(self):
        option = self.env['travel.request.option'].create({
            'travel_request_id': self.request.id,
            'option_type': 'flight',
        })
        option_id = option.id
        self.request.unlink()
        self.assertFalse(
            self.env['travel.request.option'].search([('id', '=', option_id)]))
