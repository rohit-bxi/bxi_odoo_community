# -*- coding: utf-8 -*-
from datetime import date, datetime
from unittest.mock import patch

from freezegun import freeze_time

from odoo import Command
from odoo.tests import TransactionCase, tagged


OFFICE_LAT = 12.97160000
OFFICE_LON = 77.59460000

# Asia/Kolkata = UTC+5:30. Monday 21 Sep 2026, 09:30 IST = 04:00 UTC.
MONDAY = date(2026, 9, 21)
MONDAY_CHECK_IN = datetime(2026, 9, 21, 4, 0)
TUESDAY_MORNING = '2026-09-22 04:30:00'


@tagged('post_install', '-at_install')
class TestMissedCheckout(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            'missed_checkout_lwp': True,
            'missed_checkout_lwp_start_date': date(2026, 1, 1),
            'attendance_regularization_start_date': date(2026, 1, 1),
        })

        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'Missed Check-out 40h',
            'tz': 'Asia/Kolkata',
            'company_id': cls.company.id,
            'attendance_ids': [Command.clear()] + [
                Command.create({
                    'name': 'Day %s %s' % (day, period),
                    'dayofweek': str(day),
                    'hour_from': hour_from,
                    'hour_to': hour_to,
                    'day_period': period,
                })
                for day in range(5)
                for hour_from, hour_to, period in ((9, 13, 'morning'), (14, 18, 'afternoon'))
            ],
        })

        address = cls.company.partner_id
        cls.office = cls.env['hr.work.location'].create({
            'name': 'Test Office',
            'location_type': 'office',
            'address_id': address.id,
            'company_id': cls.company.id,
            'office': True,
            'latitude': OFFICE_LAT,
            'longitude': OFFICE_LON,
            'radius_km': 1.0,
        })
        cls.home = cls.env['hr.work.location'].create({
            'name': 'Test Home',
            'location_type': 'home',
            'address_id': address.id,
            'company_id': cls.company.id,
            'home': True,
        })

        weekdays = ('monday', 'tuesday', 'wednesday', 'thursday',
                    'friday', 'saturday', 'sunday')
        cls.manager_user = cls.env['res.users'].create({
            'name': 'Missed Checkout Manager',
            'login': 'missed.checkout.manager',
            'email': 'missed.checkout.manager@example.com',
        })
        cls.manager = cls.env['hr.employee'].create({
            'name': 'Missed Checkout Manager',
            'company_id': cls.company.id,
            'user_id': cls.manager_user.id,
            'work_email': 'missed.checkout.manager@example.com',
        })
        cls.employee = cls.env['hr.employee'].create({
            'parent_id': cls.manager.id,
            'leave_manager_id': cls.manager_user.id,
            'name': 'Missed Checkout Employee',
            'company_id': cls.company.id,
            'tz': 'Asia/Kolkata',
            'work_email': 'missed.checkout@example.com',
            'date_version': date(2020, 1, 1),
            'resource_calendar_id': cls.calendar.id,
            **{'%s_location_id' % day: cls.office.id for day in weekdays},
        })

        cls.lwp_type = cls.env['hr.leave.type'].search(
            [('time_off_code', '=', 'LWP')], limit=1)
        if cls.lwp_type:
            cls.lwp_type.write({'requires_allocation': False, 'company_id': False})
        else:
            cls.lwp_type = cls.env['hr.leave.type'].create({
                'name': 'Leave Without Pay',
                'time_off_code': 'LWP',
                'requires_allocation': False,
                'leave_validation_type': 'hr',
            })

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------

    def _check_in(self, check_in=MONDAY_CHECK_IN, check_out=False):
        vals = {
            'employee_id': self.employee.id,
            'check_in': check_in,
            'latitude': OFFICE_LAT,
            'longitude': OFFICE_LON,
        }
        if check_out:
            vals['check_out'] = check_out
        return self.env['hr.attendance'].create(vals)

    def _lwp_leaves(self, day=MONDAY):
        return self.env['hr.leave'].search([
            ('employee_id', '=', self.employee.id),
            ('holiday_status_id', '=', self.lwp_type.id),
            ('request_date_from', '=', day),
        ])

    def _cutoff_lwp(self, day=MONDAY):
        """LWP applied at the cutoff for a day not regularized."""
        return self.env['hr.attendance']._create_missed_checkout_lwp(self.employee, day)

    def _run_cron(self, at=TUESDAY_MORNING):
        with freeze_time(at):
            self.env['hr.attendance']._cron_process_missed_checkouts()

    def _assert_closed(self, attendance):
        self.assertTrue(attendance.is_missed_checkout)
        self.assertTrue(attendance.is_auto_checkout)
        self.assertEqual(attendance.check_out, attendance.check_in)
        self.assertEqual(attendance.worked_hours, 0.0)

    # ------------------------------------------------------------
    # Missed check-out: closed, no LWP until the cutoff
    # ------------------------------------------------------------

    def test_office_day_missed_checkout_closes_without_lwp(self):
        attendance = self._check_in()
        self._run_cron()

        self._assert_closed(attendance)
        self.assertFalse(self._lwp_leaves())
        self.assertFalse(attendance.lwp_leave_id)
        self.assertEqual(attendance.missed_checkout_date, MONDAY)
        self.assertEqual(attendance.regularization_deadline, date(2026, 9, 25))

    def test_missed_checkout_mail_to_employee_only(self):
        attendance = self._check_in()
        self._run_cron()

        mails = self.env['mail.mail'].search([
            ('model', '=', 'hr.attendance'),
            ('res_id', '=', attendance.id),
        ])
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails.email_to, 'missed.checkout@example.com')
        self.assertFalse(mails.email_cc)
        self.assertFalse(mails.recipient_ids)
        self.assertIn('21-09-2026', mails.subject)

    def test_home_day_missed_checkout_closes_without_lwp(self):
        self.employee.monday_location_id = self.home
        attendance = self._check_in()
        self._run_cron()

        self._assert_closed(attendance)
        self.assertFalse(self._lwp_leaves())

    def test_old_auto_checkout_cron_uses_missed_checkout_logic(self):
        attendance = self._check_in()
        with freeze_time(TUESDAY_MORNING):
            self.env['hr.attendance']._cron_auto_checkout()

        self._assert_closed(attendance)

    def test_morning_session_then_open_afternoon(self):
        morning = self._check_in(check_out=datetime(2026, 9, 21, 7, 30))
        afternoon = self._check_in(check_in=datetime(2026, 9, 21, 8, 30))
        self._run_cron()

        self.assertFalse(morning.is_missed_checkout)
        self.assertEqual(morning.check_out, datetime(2026, 9, 21, 7, 30))
        self._assert_closed(afternoon)

    def test_check_in_late_evening_processed_after_local_midnight(self):
        # 23:30 IST Monday = 18:00 UTC Monday; cron at 00:30 IST Tuesday.
        attendance = self._check_in(check_in=datetime(2026, 9, 21, 18, 0))
        self._run_cron(at='2026-09-21 19:00:00')

        self._assert_closed(attendance)
        self.assertEqual(attendance.missed_checkout_date, MONDAY)

    # ------------------------------------------------------------
    # Next-day check-in
    # ------------------------------------------------------------

    def test_next_day_button_checks_in(self):
        yesterday = self._check_in()

        with freeze_time(TUESDAY_MORNING):
            today = self.employee._attendance_action_change({
                'latitude': OFFICE_LAT,
                'longitude': OFFICE_LON,
            })

        self._assert_closed(yesterday)
        self.assertNotEqual(today, yesterday)
        self.assertFalse(today.check_out)
        self.assertEqual(today.check_in, datetime(2026, 9, 22, 4, 30))
        self.assertEqual(self.employee.attendance_state, 'checked_in')

    def test_next_day_create_checks_in(self):
        yesterday = self._check_in()

        with freeze_time(TUESDAY_MORNING):
            today = self._check_in(check_in=datetime(2026, 9, 22, 4, 30))

        self._assert_closed(yesterday)
        self.assertFalse(today.check_out)

    def test_same_day_button_still_checks_out(self):
        attendance = self._check_in()

        with freeze_time('2026-09-21 12:30:00'):
            result = self.employee._attendance_action_change({
                'latitude': OFFICE_LAT,
                'longitude': OFFICE_LON,
            })

        self.assertEqual(result, attendance)
        self.assertFalse(attendance.is_missed_checkout)
        self.assertEqual(attendance.check_out, datetime(2026, 9, 21, 12, 30))

    def test_same_day_not_processed(self):
        # 23:30 IST check-in, cron at 23:45 IST the same day.
        attendance = self._check_in(check_in=datetime(2026, 9, 21, 18, 0))
        self._run_cron(at='2026-09-21 18:15:00')

        self.assertFalse(attendance.check_out)
        self.assertFalse(attendance.is_missed_checkout)

    # ------------------------------------------------------------
    # Cutoff LWP
    # ------------------------------------------------------------

    def test_cutoff_lwp_validated_and_flagged(self):
        leave, reason = self._cutoff_lwp()

        self.assertFalse(reason)
        self.assertEqual(leave, self._lwp_leaves())
        self.assertEqual(leave.state, 'validate')
        self.assertEqual(leave.number_of_days, 1.0)
        self.assertTrue(leave.is_missed_checkout_lwp)

    def test_cutoff_lwp_does_not_notify_manager_or_hr(self):
        with patch.object(
            type(self.env['hr.leave']), '_send_leave_submission_email',
        ) as submission_email:
            leave, _reason = self._cutoff_lwp()
            # Paths without the context flag must not send it either.
            leave._check_and_send_leave_notification()

        submission_email.assert_not_called()
        self.assertNotIn(self.manager_user.partner_id, leave.message_partner_ids)
        self.assertFalse(leave.activity_ids)

    def test_cutoff_lwp_weekend(self):
        leave, _reason = self._cutoff_lwp(date(2026, 9, 26))
        self.assertFalse(leave)

    def test_cutoff_lwp_public_holiday(self):
        # Created ahead of time: bxi_timesheet locks past-week timesheet
        # lines, which project_timesheet_holidays generates for holidays.
        with freeze_time('2026-09-01 04:00:00'):
            self.env['resource.calendar.leaves'].create({
                'name': 'Public Holiday',
                'calendar_id': self.calendar.id,
                'company_id': self.company.id,
                'date_from': datetime(2026, 9, 20, 18, 30),
                'date_to': datetime(2026, 9, 21, 18, 29, 59),
            })
        leave, _reason = self._cutoff_lwp()
        self.assertFalse(leave)

    def test_cutoff_lwp_existing_leave_no_duplicate(self):
        existing = self.env['hr.leave'].with_context(
            skip_sick_leave_policy=True,
            skip_leave_submission_email=True,
        ).create({
            'employee_id': self.employee.id,
            'holiday_status_id': self.lwp_type.id,
            'request_date_from': MONDAY,
            'request_date_to': MONDAY,
        })
        leave, _reason = self._cutoff_lwp()

        self.assertFalse(leave)
        self.assertEqual(self._lwp_leaves(), existing)

    def test_cutoff_lwp_twice_single_leave(self):
        self._cutoff_lwp()
        leave, _reason = self._cutoff_lwp()

        self.assertFalse(leave)
        self.assertEqual(len(self._lwp_leaves()), 1)

    def test_cutoff_lwp_client_site_day(self):
        # An approved client-site exception returns no effective location.
        with patch.object(
            type(self.env['hr.attendance']),
            '_get_effective_work_location',
            return_value=False,
        ):
            leave, _reason = self._cutoff_lwp()
        self.assertFalse(leave)

    def test_cutoff_lwp_deputation(self):
        if 'is_on_deputation' not in self.employee._fields:
            self.skipTest('bxi_international_deputation is not installed')
        self.employee.is_on_deputation = True
        leave, _reason = self._cutoff_lwp()
        self.assertFalse(leave)

    def test_cutoff_lwp_before_start_dates(self):
        self.company.missed_checkout_lwp_start_date = date(2026, 9, 22)
        self.assertFalse(self._cutoff_lwp()[0])

        self.company.missed_checkout_lwp_start_date = date(2026, 1, 1)
        self.company.attendance_regularization_start_date = date(2026, 9, 22)
        self.assertFalse(self._cutoff_lwp()[0])

    def test_cutoff_lwp_feature_disabled(self):
        self.company.missed_checkout_lwp = False
        self.assertFalse(self._cutoff_lwp()[0])

    def test_cutoff_lwp_missing_lwp_type(self):
        self.lwp_type.time_off_code = 'LWP_DISABLED'
        with self.assertLogs(
            'odoo.addons.bxi_attendance_missed_checkout.models.hr_attendance',
            level='ERROR',
        ):
            leave, _reason = self._cutoff_lwp()
        self.assertFalse(leave)

    def test_exempt_day_closed_without_reminder(self):
        self.company.missed_checkout_lwp = False
        attendance = self._check_in()
        self._run_cron()

        self._assert_closed(attendance)
        self.assertFalse(self.env['mail.mail'].search([
            ('model', '=', 'hr.attendance'),
            ('res_id', '=', attendance.id),
        ]))

    # ------------------------------------------------------------
    # Regularization cycle
    # ------------------------------------------------------------

    def test_regularization_cycle(self):
        Attendance = self.env['hr.attendance']
        self.assertEqual(
            Attendance._get_regularization_cycle(date(2026, 10, 25)),
            (date(2026, 9, 26), date(2026, 10, 25)))
        self.assertEqual(
            Attendance._get_regularization_cycle(date(2026, 10, 26)),
            (date(2026, 10, 26), date(2026, 11, 25)))
        self.assertEqual(
            Attendance._get_regularization_cycle(date(2026, 12, 31)),
            (date(2026, 12, 26), date(2027, 1, 25)))
        self.assertEqual(
            Attendance._get_regularization_cycle(date(2027, 1, 10)),
            (date(2026, 12, 26), date(2027, 1, 25)))
        self.assertEqual(
            Attendance._get_last_closed_regularization_cycle(date(2026, 10, 26)),
            (date(2026, 9, 26), date(2026, 10, 25)))
        self.assertEqual(
            Attendance._get_last_closed_regularization_cycle(date(2026, 10, 7)),
            (date(2026, 8, 26), date(2026, 9, 25)))
