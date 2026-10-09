# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestTravelRequest(TransactionCase):
    """Business-logic tests for the employee → manager → HR → myBiz workflow.

    bxi_mybiz_integration (when installed alongside this module, as in a
    normal deployment) overrides the config's required credential fields
    and the travel.request push/payload methods entirely. The myBiz-facing
    tests below detect whether that override is active and assert against
    whichever contract is actually executing, instead of assuming this
    module is ever installed in isolation.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.has_override = 'partner_api_key' in cls.env['bxi.mybiz.config']._fields
        cls.travel_group = cls.env.ref('bxi_travel_request.group_travel_user')
        cls.travel_manager_group = cls.env.ref('bxi_travel_request.group_travel_manager')
        cls.department = cls.env['hr.department'].create({'name': 'Engineering'})

        # group_travel_manager (not just group_travel_user) is required for the
        # "own + team" record rule that lets a manager write to a subordinate's
        # travel request — without it, ir.rule falls back to the base "own
        # requests only" rule and every approval write is denied.
        cls.manager_user = cls._create_user(
            'Alice Manager', 'alice.manager@example.com',
            extra_groups=cls.travel_manager_group)
        cls.manager_employee = cls.env['hr.employee'].create({
            'name': 'Alice Manager',
            'user_id': cls.manager_user.id,
            'department_id': cls.department.id,
            'work_email': 'alice.manager@example.com',
        })

        cls.employee_user = cls._create_user('Bob Employee', 'bob.employee@example.com')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Bob Employee',
            'user_id': cls.employee_user.id,
            'department_id': cls.department.id,
            'parent_id': cls.manager_employee.id,
            'work_email': 'bob.employee@example.com',
        })

        cls.hr_group = cls.env.ref('hr.group_hr_user')
        cls.hr_user = cls._create_user(
            'Carol HR', 'carol.hr@example.com', extra_groups=cls.hr_group)

        config_vals = {
            'name': 'Test myBiz Config',
            'client_id': 'CLIENT123',
            'org_id': 'ORG123',
            'api_key': 'SECRET123',
        }
        if cls.has_override:
            config_vals.update({'partner_api_key': 'PARTNER123', 'client_code': 'CODE123'})
        cls.mybiz_config = cls.env['bxi.mybiz.config'].create(config_vals)

    @classmethod
    def _create_user(cls, name, login, extra_groups=None):
        group_commands = [(4, cls.env.ref('base.group_user').id), (4, cls.travel_group.id)]
        if extra_groups:
            group_commands.append((4, extra_groups.id))
        return cls.env['res.users'].create({
            'name': name,
            'login': login,
            'email': login,
            'group_ids': group_commands,
        })

    def _create_travel_request(self, **overrides):
        vals = {
            'employee_id': self.employee.id,
            'travel_purpose': 'Client site visit',
            'from_city': 'Bengaluru',
            'to_city': 'Hyderabad',
            'departure_date': '2030-01-10',
            'return_date': '2030-01-12',
            'mode_of_travel': 'flight',
        }
        vals.update(overrides)
        return self.env['travel.request'].create(vals)

    # ── Identity / sequence ─────────────────────────────────────────

    def test_sequence_is_assigned_on_create(self):
        record = self._create_travel_request()
        self.assertNotEqual(record.name, 'New')
        self.assertTrue(record.name.startswith('BXI/TR/'))

    def test_days_computed_from_dates(self):
        record = self._create_travel_request(
            departure_date='2030-01-10', return_date='2030-01-12')
        self.assertEqual(record.days, 3)

    # ── Constraints ──────────────────────────────────────────────────

    def test_return_before_departure_raises(self):
        with self.assertRaises(UserError):
            self._create_travel_request(
                departure_date='2030-01-12', return_date='2030-01-10')

    def test_hotel_checkout_before_checkin_raises(self):
        with self.assertRaises(UserError):
            self._create_travel_request(
                hotel_required=True,
                hotel_checkin='2030-01-10',
                hotel_checkout='2030-01-09',
            )

    # ── Submit workflow ────────────────────────────────────────────

    def test_submit_without_segment_raises(self):
        record = self._create_travel_request()
        with self.assertRaises(UserError):
            record.action_submit()

    def test_submit_with_segment_moves_to_manager_approval(self):
        record = self._create_travel_request()
        self.env['travel.request.option'].create({
            'travel_request_id': record.id,
            'option_type': 'flight',
            'origin_code': 'BLR',
            'destination_code': 'HYD',
        })
        record.action_submit()
        self.assertEqual(record.state, 'manager_approval')

    # ── Manager approval ─────────────────────────────────────────────

    def _submitted_request(self):
        record = self._create_travel_request()
        self.env['travel.request.option'].create({
            'travel_request_id': record.id,
            'option_type': 'flight',
            'origin_code': 'BLR',
            'destination_code': 'HYD',
        })
        record.action_submit()
        return record

    def test_non_manager_cannot_approve(self):
        record = self._submitted_request()
        with self.assertRaises(UserError):
            record.with_user(self.employee_user).manager_action_approve()

    def test_manager_can_approve_moves_to_hr_approval(self):
        record = self._submitted_request()
        record.with_user(self.manager_user).manager_action_approve()
        self.assertEqual(record.state, 'hr_approval')
        self.assertEqual(record.manager_approved_by, self.manager_employee)

    def test_manager_refuse_cancels_request(self):
        record = self._submitted_request()
        record.with_user(self.manager_user).manager_action_refuse()
        self.assertEqual(record.state, 'cancelled')

    # ── HR approval + myBiz push ─────────────────────────────────────

    def _hr_pending_request(self):
        record = self._submitted_request()
        record.with_user(self.manager_user).manager_action_approve()
        return record

    def test_non_hr_cannot_approve(self):
        record = self._hr_pending_request()
        with self.assertRaises(UserError):
            record.with_user(self.employee_user).hr_action_approve()

    @patch('requests.post')
    def test_hr_approve_pushes_to_mybiz_success(self, mock_post):
        mock_response = MagicMock()
        if self.has_override:
            # Real myBiz contract: success is signalled by status == 'success'.
            mock_response.json.return_value = {
                'status': 'success', 'travelRequestUrl': 'https://mybiz.example.com/trf/1'}
        else:
            mock_response.json.return_value = {'serviceId': 'SVC-001', 'bookingRef': 'PNR123'}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        record = self._hr_pending_request()
        record.with_user(self.hr_user).hr_action_approve()

        self.assertEqual(record.state, 'mybiz_pending')
        self.assertEqual(record.mybiz_status, 'pending')
        if self.has_override:
            self.assertEqual(
                record.mybiz_travel_request_url, 'https://mybiz.example.com/trf/1')
        else:
            self.assertEqual(record.mybiz_service_id, 'SVC-001')
            self.assertEqual(record.mybiz_booking_ref, 'PNR123')
        mock_post.assert_called_once()

    @patch('requests.post')
    def test_hr_approve_push_http_error_marks_failed(self, mock_post):
        import requests as requests_lib

        mock_response = MagicMock(status_code=500, text='Internal Server Error')
        error = requests_lib.exceptions.HTTPError(response=mock_response)
        mock_post.return_value.raise_for_status.side_effect = error

        record = self._hr_pending_request()
        record.with_user(self.hr_user).hr_action_approve()

        self.assertEqual(record.mybiz_status, 'failed')
        self.assertIn('500', record.mybiz_error)

    def test_push_without_config_marks_failed(self):
        self.mybiz_config.active = False
        record = self._hr_pending_request()
        record.with_user(self.hr_user).hr_action_approve()
        self.assertEqual(record.mybiz_status, 'failed')
        self.assertIn('configuration not found', record.mybiz_error)

    def test_hr_refuse_cancels_request(self):
        record = self._hr_pending_request()
        record.with_user(self.hr_user).hr_action_refuse()
        self.assertEqual(record.state, 'cancelled')

    # ── Cancel / reset ────────────────────────────────────────────────

    def test_cannot_cancel_approved_request(self):
        record = self._hr_pending_request()
        record.state = 'approved'
        with self.assertRaises(UserError):
            record.action_cancel()

    def test_reset_to_draft_requires_system_admin(self):
        record = self._hr_pending_request()
        with self.assertRaises(UserError):
            record.with_user(self.employee_user).action_reset_to_draft()

    def test_retry_push_invalid_state_raises(self):
        record = self._create_travel_request()
        with self.assertRaises(UserError):
            record.action_retry_mybiz_push()

    # ── Payload building ──────────────────────────────────────────────

    def test_build_mybiz_payload_contains_traveller_and_flight(self):
        record = self._hr_pending_request()
        payload = record._build_mybiz_payload()
        if self.has_override:
            # Real myBiz contract: services.FLIGHT[], travellerDetails.paxDetails[].
            pax_details = payload['travellerDetails']['paxDetails']
            self.assertEqual(pax_details[0]['name'], self.employee.name)
            self.assertIn('FLIGHT', payload['services'])
            self.assertEqual(payload['services']['FLIGHT'][0]['travelClass'], 'ECONOMY')
            self.assertEqual(payload['trfId'], record.name)
        else:
            self.assertEqual(payload['travellerDetails'][0]['name'], self.employee.name)
            self.assertIn('flightDetails', payload)
            self.assertEqual(payload['flightDetails']['travelClass'], 'ECONOMY')
            self.assertEqual(payload['internalReference'], record.name)
