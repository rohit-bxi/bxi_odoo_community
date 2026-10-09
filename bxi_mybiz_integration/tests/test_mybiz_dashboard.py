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
                    'recent_failures', 'dept_spend', 'monthly_trend',
                    'base_domain', 'recent_domain'):
            self.assertIn(key, data)

    def test_dashboard_domains_support_drill_down_filtering(self):
        # The dashboard client composes these domains with an extra
        # status/department/date filter to open a matching list view, so
        # they must actually scope 'travel.request' searches correctly.
        data = self.dashboard.get_dashboard_data(days=365)
        TravelRequest = self.env['travel.request'].sudo()

        pending_manager_domain = data['base_domain'] + [
            ('state', '=', 'manager_approval'),
        ]
        self.assertIn(
            self.pending_manager_request,
            TravelRequest.search(pending_manager_domain),
        )

        failed_domain = data['recent_domain'] + [
            ('mybiz_status', '=', 'failed'),
        ]
        self.assertIn(
            self.failed_request, TravelRequest.search(failed_domain))

    def test_dept_spend_entries_include_department_id(self):
        data = self.dashboard.get_dashboard_data(days=365)
        sales_entry = next(
            d for d in data['dept_spend'] if d['department'] == 'Sales')
        self.assertEqual(sales_entry['department_id'], self.department.id)

    def test_monthly_trend_entries_include_date_bounds(self):
        data = self.dashboard.get_dashboard_data(days=365)
        for month in data['monthly_trend']:
            self.assertIn('date_from', month)
            self.assertIn('date_to', month)
            self.assertLess(month['date_from'], month['date_to'])

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
