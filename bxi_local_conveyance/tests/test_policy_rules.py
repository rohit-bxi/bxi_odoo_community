from datetime import datetime, time, timedelta

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import ConveyanceCommon


@tagged('post_install', '-at_install')
class TestPolicyRules(ConveyanceCommon):

    # ── Travel plans and rates ───────────────────────────────────────────
    def test_travel_plan_follows_band_level(self):
        self.assertEqual(self.senior.conveyance_travel_plan_id, self.env.ref('bxi_local_conveyance.travel_plan_tp1'))
        self.assertEqual(self.manager.conveyance_travel_plan_id, self.env.ref('bxi_local_conveyance.travel_plan_tp1'))
        self.assertEqual(self.employee.conveyance_travel_plan_id, self.env.ref('bxi_local_conveyance.travel_plan_tp2'))
        self.assertEqual(self.junior.conveyance_travel_plan_id, self.env.ref('bxi_local_conveyance.travel_plan_tp3'))
        self.employee.role_band = False
        self.assertFalse(self.employee.conveyance_travel_plan_id)

    def test_travel_plans_cannot_overlap(self):
        with self.assertRaisesRegex(Exception, 'overlap'):
            self.env['bxi.conveyance.travel.plan'].create({'name': 'TPX', 'band_min': 5, 'band_max': 6})

    def test_personal_vehicle_paid_per_km(self):
        two_wheeler = self._claim(self.product_2w, conveyance_distance=12)
        four_wheeler = self._claim(self.product_4w, conveyance_distance=12)
        self.assertEqual(two_wheeler.total_amount, 30.0)
        self.assertEqual(four_wheeler.total_amount, 60.0)
        # Whatever the travel plan.
        self.assertEqual(self._claim(self.product_4w, employee=self.junior, conveyance_distance=12).total_amount, 60.0)
        self._submit(two_wheeler)
        self.assertEqual(two_wheeler.state, 'conveyance_approval')
        self.assertEqual(two_wheeler.conveyance_travel_plan_id, self.employee.conveyance_travel_plan_id)

    def test_personal_vehicle_needs_distance(self):
        with self.assertRaisesRegex(UserError, 'distance'):
            self._submit(self._claim(self.product_2w, conveyance_distance=0))

    # ── Clause 8: claim window and other office ──────────────────────────
    def test_claimed_within_45_days(self):
        # The 45th day may be a weekend: send those to HR instead of refusing them.
        self.env['ir.config_parameter'].sudo().set_param('bxi_local_conveyance.non_working_day_mode', 'flag')
        self._submit(self._claim(self.product_2w, date=self.today - timedelta(days=45)))
        with self.assertRaisesRegex(UserError, '45 days'):
            self._submit(self._claim(self.product_2w, date=self.today - timedelta(days=46)))

    def test_future_date_refused(self):
        with self.assertRaisesRegex(UserError, 'future'):
            self._submit(self._claim(self.product_2w, date=self.today + timedelta(days=1)))

    def test_other_office_covered_two_months(self):
        office = self.env['hr.work.location'].create({
            'name': 'Noida Office', 'location_type': 'office',
            'address_id': self.company.partner_id.id,
        })
        assignment = self.env['bxi.conveyance.office.assignment'].create({
            'employee_id': self.employee.id, 'work_location_id': office.id,
            'date_from': self.workday - timedelta(days=90),
        })
        with self.assertRaisesRegex(UserError, 'covered until'):
            self._submit(self._claim(self.product_2w))
        assignment.date_from = self.workday - timedelta(days=20)
        self._submit(self._claim(self.product_2w))

    # ── Clause 5: weekends and holidays ──────────────────────────────────
    def test_weekend_refused(self):
        with self.assertRaisesRegex(UserError, 'weekend or holiday'):
            self._submit(self._claim(self.product_2w, date=self.weekend_day))

    def test_public_holiday_refused(self):
        self.env['resource.calendar.leaves'].create({
            'name': 'Holiday', 'calendar_id': self.calendar.id, 'company_id': self.company.id,
            'date_from': datetime.combine(self.workday, time.min) - timedelta(hours=6),
            'date_to': datetime.combine(self.workday, time.max),
        })
        with self.assertRaisesRegex(UserError, 'weekend or holiday'):
            self._submit(self._claim(self.product_2w))

    def test_weekend_flagged_for_hr(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_local_conveyance.non_working_day_mode', 'flag')
        claim = self._submit(self._claim(self.product_2w, date=self.weekend_day))
        self.assertIn('weekend', claim.conveyance_policy_note)
        self.assertEqual(claim.conveyance_approval_line_ids.mapped('role'), ['rm', 'hr'])

    # ── Clauses 2, 4, 7 and exceptions ───────────────────────────────────
    def test_travel_within_city_only(self):
        with self.assertRaisesRegex(UserError, 'Intercity'):
            self._submit(self._claim(self.product_2w, conveyance_within_city=False))

    def test_between_company_sites_only_emergency_auto(self):
        with self.assertRaisesRegex(UserError, 'inter-office cabs'):
            self._submit(self._claim(self.product_2w, conveyance_purpose='inter_site'))
        with self.assertRaisesRegex(UserError, 'inter-office cabs'):
            self._submit(self._claim(self.product_auto, employee=self.junior, conveyance_purpose='inter_site'))
        claim = self._claim(self.product_auto, conveyance_purpose='inter_site', conveyance_is_emergency=True,
                            conveyance_reason='No cab, no vehicle')
        self._submit(claim)
        self.assertEqual(claim.state, 'conveyance_approval')

    def test_airport_one_way_per_km(self):
        with self.assertRaisesRegex(UserError, 'per-km'):
            self._submit(self._claim(self.product_taxi, conveyance_purpose='airport',
                                     conveyance_airport_leg='to_airport'))
        with self.assertRaisesRegex(UserError, 'airport leg'):
            self._submit(self._claim(self.product_4w, conveyance_purpose='airport'))
        self._submit(self._claim(self.product_4w, conveyance_purpose='airport', conveyance_airport_leg='to_airport'))
        with self.assertRaisesRegex(UserError, 'one way'):
            self._submit(self._claim(self.product_4w, conveyance_purpose='airport',
                                     conveyance_airport_leg='to_airport'))
        self._submit(self._claim(self.product_4w, conveyance_purpose='airport', conveyance_airport_leg='from_airport'))

    # ── Travel plan table ────────────────────────────────────────────────
    def test_auto_outside_emergency_for_tp3_only(self):
        with self.assertRaisesRegex(UserError, 'emergency'):
            self._submit(self._claim(self.product_auto))
        with self.assertRaisesRegex(UserError, 'describe the emergency'):
            self._submit(self._claim(self.product_auto, conveyance_is_emergency=True))
        self._submit(self._claim(self.product_auto, conveyance_is_emergency=True, conveyance_reason='Cab missed'))
        self._submit(self._claim(self.product_auto, employee=self.junior))

    def test_taxi_for_tp3_where_no_auto(self):
        self._submit(self._claim(self.product_taxi))
        self._submit(self._claim(self.product_taxi, employee=self.senior))
        with self.assertRaisesRegex(UserError, 'no auto-rickshaw'):
            self._submit(self._claim(self.product_taxi, employee=self.junior))
        self._submit(self._claim(self.product_taxi, employee=self.junior, conveyance_reason='No auto at night'))

    def test_taxi_needs_band(self):
        self.employee.role_band = False
        with self.assertRaisesRegex(UserError, 'no travel plan'):
            self._submit(self._claim(self.product_taxi))

    # ── Bills and clause 3 ───────────────────────────────────────────────
    def test_bill_required(self):
        with self.assertRaisesRegex(UserError, 'attach the bill'):
            self._submit(self._claim(self.product_taxi, receipt=False))

    def test_same_bill_not_claimed_twice(self):
        # e.g. a fuel bill already reimbursed through the flexi basket.
        first = self._claim(self.product_taxi, receipt=False)
        self._receipt(first.sudo(), b'Same bill')
        self._submit(first)
        second = self._claim(self.product_taxi, receipt=False)
        self._receipt(second.sudo(), b'Same bill')
        with self.assertRaisesRegex(UserError, 'already been claimed'):
            self._submit(second)

    def test_same_bill_number_not_claimed_twice(self):
        self._submit(self._claim(self.product_taxi, conveyance_bill_number='INV-42'))
        with self.assertRaisesRegex(UserError, 'already been claimed'):
            self._submit(self._claim(self.product_taxi, conveyance_bill_number='inv-42 '))

    # ── Clause 6: parking and toll ───────────────────────────────────────
    def test_parking_with_a_trip(self):
        with self.assertRaisesRegex(UserError, 'along with a conveyance claim'):
            self._submit(self._claim(self.product_parking))
        trip = self._claim(self.product_4w)
        parking = self._claim(self.product_parking, conveyance_parent_id=trip.id)
        with self.assertRaisesRegex(UserError, 'first, or together'):
            self._submit(parking)
        (parking | trip).with_user(self.employee.user_id).action_submit()
        self.assertEqual(parking.state, 'conveyance_approval')
        self.assertEqual(parking.conveyance_approval_line_ids.mapped('role'), ['rm', 'hr'])

    def test_parking_of_another_day_refused(self):
        trip = self._submit(self._claim(self.product_4w))
        parking = self._claim(self.product_parking, conveyance_parent_id=trip.id,
                              date=self.workday - timedelta(days=1))
        with self.assertRaisesRegex(UserError, 'same day'):
            self._submit(parking)

    # ── Food Policy ──────────────────────────────────────────────────────
    def test_food_for_sales_team_only(self):
        with self.assertRaisesRegex(UserError, 'Sales Team'):
            self._submit(self._claim(self.product_food))

    def test_food_capped_per_day(self):
        claim = self._submit(self._claim(self.product_food, employee=self.salesman, total_amount_currency=1200))
        self.assertEqual(claim.total_amount, 1000)
        self.assertEqual(claim.conveyance_bill_amount, 1200)
        self.assertIn('borne by the employee', claim.conveyance_policy_note)
        # A capped claim needs no HR review.
        self.assertEqual(claim.conveyance_approval_line_ids.mapped('role'), ['rm'])
        with self.assertRaisesRegex(UserError, 'already been claimed'):
            self._submit(self._claim(self.product_food, employee=self.salesman, total_amount_currency=100))

    def test_food_remaining_limit(self):
        self._submit(self._claim(self.product_food, employee=self.salesman, total_amount_currency=600))
        second = self._submit(self._claim(self.product_food, employee=self.salesman, total_amount_currency=600))
        self.assertEqual(second.total_amount, 400)

    # ── Isolation ────────────────────────────────────────────────────────
    def test_conveyance_not_on_generic_expense_portal(self):
        products = self.env['product.product'].search(self.env['hr.expense']._portal_expense_product_domain())
        self.assertFalse(products.filtered('conveyance_kind'))

    def test_submitted_claim_locked(self):
        claim = self._submit(self._claim(self.product_2w))
        with self.assertRaisesRegex(UserError, 'cannot be modified'):
            claim.with_user(self.hr_user).conveyance_distance = 50
