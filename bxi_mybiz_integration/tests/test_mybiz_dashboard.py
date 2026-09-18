# -*- coding: utf-8 -*-
from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMybizDashboard(TransactionCase):
    """Tests for the myBiz Integration Dashboard aggregation API."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dashboard = cls.env['bxi.mybiz.dashboard']
        cls.department = cls.env['hr.department'].create({'name': 'Sales'})
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Dashboard Tester',
            'department_id': cls.department.id,
        })

        cls.approved_request = cls.env['travel.request'].create({
            'employee_id': cls.employee.id,
            'department_id': cls.department.id,
            'travel_purpose': 'Site visit',
            'from_city': 'Mumbai',
            'to_city': 'Pune',
            'departure_date': '2030-06-01',
            'state': 'approved',
            'mybiz_status': 'booked',
        })
        cls.failed_request = cls.env['travel.request'].create({
            'employee_id': cls.employee.id,
            'department_id': cls.department.id,
            'travel_purpose': 'Conference',
            'from_city': 'Mumbai',
            'to_city': 'Goa',
            'departure_date': '2030-06-10',
            'state': 'mybiz_pending',
            'mybiz_status': 'failed',
            'mybiz_error': 'Timeout while contacting myBiz.',
            # Force this to sort first in the "recent failures" list (ordered
            # by mybiz_sync_date desc) regardless of other data in the database.
            'mybiz_sync_date': fields.Datetime.now(),
        })
        cls.pending_manager_request = cls.env['travel.request'].create({
            'employee_id': cls.employee.id,
            'department_id': cls.department.id,
            'travel_purpose': 'Training',
            'from_city': 'Mumbai',
            'to_city': 'Delhi',
            'departure_date': '2030-06-15',
            'state': 'manager_approval',
        })

    def test_dashboard_data_has_expected_keys(self):
        data = self.dashboard.get_dashboard_data(days=365)
        for key in ('total_requests', 'state_counts', 'mybiz_counts',
                    'success_rate', 'pending_manager', 'upcoming',
                    'recent_failures', 'dept_spend', 'monthly_trend'):
            self.assertIn(key, data)

    def test_dashboard_counts_include_seeded_requests(self):
        data = self.dashboard.get_dashboard_data(days=365)
        self.assertGreaterEqual(data['total_requests'], 3)
        self.assertGreaterEqual(data['state_counts']['approved'], 1)
        self.assertGreaterEqual(data['state_counts']['manager_approval'], 1)
        self.assertGreaterEqual(data['pending_manager'], 1)

    def test_dashboard_lists_recent_failure(self):
        data = self.dashboard.get_dashboard_data(days=365)
        failure_names = [f['name'] for f in data['recent_failures']]
        self.assertIn(self.failed_request.name, failure_names)

    def test_dashboard_invalid_days_falls_back_to_default(self):
        data = self.dashboard.get_dashboard_data(days='not-a-number')
        self.assertEqual(data['days'], 90)

    def test_dashboard_respects_date_window(self):
        # bxi_uat is a shared database that may already hold unrelated travel
        # requests, so assert on the delta our own fixture causes rather than
        # on absolute counts.
        before_wide = self.dashboard.get_dashboard_data(days=3650)['total_requests']
        before_narrow = self.dashboard.get_dashboard_data(days=1)['total_requests']

        self.env['travel.request'].create({
            'employee_id': self.employee.id,
            'department_id': self.department.id,
            'travel_purpose': 'Old trip outside the window',
            'from_city': 'Mumbai',
            'to_city': 'Surat',
            'departure_date': '2020-01-01',
            'request_date': '2020-01-01',
        })

        after_wide = self.dashboard.get_dashboard_data(days=3650)['total_requests']
        after_narrow = self.dashboard.get_dashboard_data(days=1)['total_requests']

        # A 10-year window must pick up the old request...
        self.assertEqual(after_wide, before_wide + 1)
        # ...but a 1-day window must exclude it.
        self.assertEqual(after_narrow, before_narrow)
