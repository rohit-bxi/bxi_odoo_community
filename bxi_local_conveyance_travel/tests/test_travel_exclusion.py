from datetime import timedelta

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.bxi_local_conveyance.tests.common import ConveyanceCommon


@tagged('post_install', '-at_install')
class TestTravelExclusion(ConveyanceCommon):

    def _travel(self, state='approve', departure=None, back=None):
        departure = departure or self.workday - timedelta(days=1)
        return self.env['travel.request'].sudo().create({
            'employee_id': self.employee.id,
            'from_city': 'Delhi',
            'to_city': 'Mumbai',
            'travel_purpose': 'Client workshop',
            'departure_date': departure,
            'return_date': back or self.workday + timedelta(days=1),
            'state': state,
        })

    def test_no_conveyance_during_travel(self):
        self._travel()
        with self.assertRaisesRegex(UserError, 'travel request'):
            self._submit(self._claim(self.product_2w))
        with self.assertRaisesRegex(UserError, 'travel request'):
            self._submit(self._claim(self.product_taxi))

    def test_pending_travel_counts(self):
        self._travel(state='hr_approval')
        with self.assertRaisesRegex(UserError, 'travel request'):
            self._submit(self._claim(self.product_2w))

    def test_airport_on_departure_day(self):
        self._travel(departure=self.workday)
        self._submit(self._claim(self.product_4w, conveyance_purpose='airport', conveyance_airport_leg='to_airport'))
        with self.assertRaisesRegex(UserError, 'travel request'):
            self._submit(self._claim(self.product_2w))

    def test_conveyance_outside_travel(self):
        self._travel(departure=self.workday + timedelta(days=1), back=self.workday + timedelta(days=3))
        self._submit(self._claim(self.product_2w))

    def test_cancelled_travel_ignored(self):
        self._travel(state='cancel')
        self._submit(self._claim(self.product_2w))
