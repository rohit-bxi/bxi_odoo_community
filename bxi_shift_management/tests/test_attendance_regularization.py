# -*- coding: utf-8 -*-
from datetime import date, datetime
from unittest.mock import patch

from freezegun import freeze_time

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


# Asia/Kolkata = UTC+5:30. The week of Monday 21 Sep 2026 belongs to the
# cycle 26 Aug - 25 Sep 2026.
MONDAY = date(2026, 9, 21)
TUESDAY = date(2026, 9, 22)
WEDNESDAY = date(2026, 9, 23)
OPEN_CYCLE = '2026-09-24 04:00:00'      # Thursday 09:30 IST, before the cutoff
AFTER_CUTOFF = '2026-09-26 04:00:00'    # Saturday 09:30 IST, cutoff passed


@tagged('post_install', '-at_install')
class TestAttendanceRegularization(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            'missed_checkout_lwp': True,
            'missed_checkout_lwp_start_date': date(2026, 1, 1),
            # Only the tested week counts.
            'attendance_regularization_start_date': MONDAY,
            # Timesheet gaps are tested on their own.
            'timesheet_check_start_date': False,
        })

        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'Regularization 40h',
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

        cls.office = cls.env['hr.work.location'].create({
            'name': 'Regularization Office',
            'location_type': 'office',
            'address_id': cls.company.partner_id.id,
            'company_id': cls.company.id,
            'office': True,
            'latitude': 12.9716,
            'longitude': 77.5946,
            'radius_km': 1.0,
        })

        cls.manager_user = cls.env['res.users'].create({
            'name': 'Regularization Manager',
            'login': 'regularization.manager',
            'email': 'regularization.manager@example.com',
            'group_ids': [Command.set([
                cls.env.ref('bxi_shift_management.group_shift_hr').id,
            ])],
        })
        cls.manager = cls.env['hr.employee'].create({
            'name': 'Regularization Manager',
            'company_id': cls.company.id,
            'user_id': cls.manager_user.id,
            'work_email': 'regularization.manager@example.com',
        })

        weekdays = ('monday', 'tuesday', 'wednesday', 'thursday',
                    'friday', 'saturday', 'sunday')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Regularization Employee',
            'company_id': cls.company.id,
            'parent_id': cls.manager.id,
            'tz': 'Asia/Kolkata',
            'work_email': 'regularization.employee@example.com',
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

        Attendance = cls.env['hr.attendance']
        # Monday 09:30 IST: missed check-out, closed with zero duration.
        cls.missed = Attendance.create({
            'employee_id': cls.employee.id,
            'check_in': datetime(2026, 9, 21, 4, 0),
            'check_out': datetime(2026, 9, 21, 4, 0),
            'is_auto_checkout': True,
            'is_missed_checkout': True,
        })
        # Tuesday 09:00 - 18:00 IST: complete attendance.
        Attendance.create({
            'employee_id': cls.employee.id,
            'check_in': datetime(2026, 9, 22, 3, 30),
            'check_out': datetime(2026, 9, 22, 12, 30),
            'is_auto_checkout': True,
        })
        # Wednesday: no attendance at all.

        cls.project = cls.env['project.project'].create({
            'name': 'Regularization Project',
            'allow_timesheets': True,
            'company_id': cls.company.id,
        })

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------

    def _request(self, day=MONDAY, category='attendance_regularization', **vals):
        return self.env['bxi.shift.exception'].create({
            'employee_id': self.employee.id,
            'category': category,
            'date_from': day,
            'date_to': day,
            'regularize_check_in': 9.0,
            'regularize_check_out': 18.0,
            'reason': 'Forgot to check out',
            **vals,
        })

    def _unregularized(self, date_from=MONDAY, date_to=WEDNESDAY):
        return self.env['bxi.shift.exception']._get_unregularized_days(
            self.employee, date_from, date_to,
        ).get(self.employee.id, [])

    def _lwp_leaves(self, day=MONDAY):
        return self.env['hr.leave'].search([
            ('employee_id', '=', self.employee.id),
            ('request_date_from', '=', day),
            ('is_missed_checkout_lwp', '=', True),
            ('state', 'not in', ('refuse', 'cancel')),
        ])

    def _approve(self, request):
        request.with_user(self.manager_user).action_manager_approve()

    def _gaps(self, date_from=MONDAY, date_to=WEDNESDAY):
        return self.env['bxi.shift.exception']._get_regularization_gaps(
            self.employee, date_from, date_to,
        ).get(self.employee.id, {})

    def _log_timesheet(self, day):
        # bxi_timesheet locks past weeks: log within the week.
        with freeze_time(OPEN_CYCLE):
            return self.env['account.analytic.line'].create({
                'name': 'Work',
                'project_id': self.project.id,
                'employee_id': self.employee.id,
                'date': day,
                'unit_amount': 8.0,
            })

    # ------------------------------------------------------------
    # Category and single date
    # ------------------------------------------------------------

    def test_existing_flow_defaults_to_exception(self):
        request = self.env['bxi.shift.exception'].create({
            'employee_id': self.employee.id,
            'date_from': MONDAY,
            'date_to': WEDNESDAY,
        })
        self.assertEqual(request.category, 'exception')
        self.assertFalse(request.is_regularization)
        self.assertEqual(request.date_to, WEDNESDAY)

    def test_regularization_is_single_day(self):
        request = self._request(date_to=WEDNESDAY, mode='home')
        self.assertTrue(request.is_regularization)
        self.assertEqual(request.date_to, MONDAY)
        self.assertFalse(request.mode)

        request.date_from = WEDNESDAY
        self.assertEqual(request.date_to, WEDNESDAY)

    def test_all_regularization_categories(self):
        for category in ('missing_timesheet', 'late_checkout'):
            request = self._request(day=WEDNESDAY, category=category)
            self.assertTrue(request.is_regularization)
            request.unlink()

    def test_check_out_must_follow_check_in(self):
        with self.assertRaises(ValidationError):
            self._request(regularize_check_in=18.0, regularize_check_out=9.0)

    # ------------------------------------------------------------
    # Days to regularize
    # ------------------------------------------------------------

    def test_unregularized_days(self):
        # Monday missed check-out, Wednesday no attendance; Tuesday complete.
        self.assertEqual(self._unregularized(), [MONDAY, WEDNESDAY])

    def test_weekend_not_unregularized(self):
        self.assertEqual(self._unregularized(date(2026, 9, 26), date(2026, 9, 27)), [])

    def test_only_approved_request_regularizes_day(self):
        with freeze_time(OPEN_CYCLE):
            request = self._request(day=WEDNESDAY)
            request.action_submit()
            self.assertEqual(self._unregularized(), [MONDAY, WEDNESDAY])
            self._approve(request)
        self.assertEqual(self._unregularized(), [MONDAY])

    def test_draft_request_does_not_regularize_day(self):
        self._request(day=WEDNESDAY)
        self.assertEqual(self._unregularized(), [MONDAY, WEDNESDAY])

    def test_leave_day_not_unregularized(self):
        self.env['hr.leave'].with_context(
            skip_sick_leave_policy=True,
            skip_leave_submission_email=True,
        ).create({
            'employee_id': self.employee.id,
            'holiday_status_id': self.lwp_type.id,
            'request_date_from': WEDNESDAY,
            'request_date_to': WEDNESDAY,
        })
        self.assertEqual(self._unregularized(), [MONDAY])

    def test_days_before_joining_not_unregularized(self):
        self.employee.emp_date_of_joining = TUESDAY
        self.assertEqual(self._unregularized(), [WEDNESDAY])

    # ------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------

    def test_duplicate_request_rejected(self):
        with freeze_time(OPEN_CYCLE):
            self._request().action_submit()
            with self.assertRaises(UserError):
                self._request(category='late_checkout').action_submit()

    def test_closed_cycle_rejected_for_employee(self):
        request = self._request()
        with freeze_time(AFTER_CUTOFF), patch.object(
            type(self.env['res.users']), 'has_group', return_value=False,
        ):
            with self.assertRaises(UserError):
                request._validate_regularization_submit()

    def test_closed_cycle_allowed_for_hr(self):
        request = self._request()
        with freeze_time(AFTER_CUTOFF), patch.object(
            type(self.env['res.users']), 'has_group', return_value=True,
        ):
            request._validate_regularization_submit()

    def test_non_working_day_rejected(self):
        request = self._request(day=date(2026, 9, 26))
        with freeze_time('2026-09-28 04:00:00'):
            with self.assertRaises(UserError):
                request._validate_regularization_submit()

    # ------------------------------------------------------------
    # Approval
    # ------------------------------------------------------------

    def test_approve_corrects_missed_attendance(self):
        with freeze_time(OPEN_CYCLE):
            request = self._request()
            request.action_submit()
            self._approve(request)

        self.assertEqual(request.state, 'approved')
        self.assertEqual(request.attendance_id, self.missed)
        self.assertFalse(request.attendance_created)
        # 09:00 - 18:00 IST
        self.assertEqual(self.missed.check_in, datetime(2026, 9, 21, 3, 30))
        self.assertEqual(self.missed.check_out, datetime(2026, 9, 21, 12, 30))
        self.assertEqual(self.missed.regularization_id, request)
        # Shift 09-13 + 14-18, no lunch line in this schedule.
        self.assertAlmostEqual(request.regularized_shift_hours, 8.0)

    def test_approve_creates_missing_attendance(self):
        with freeze_time(OPEN_CYCLE):
            request = self._request(day=WEDNESDAY, regularize_check_in=10.0)
            request.action_submit()
            self._approve(request)

        self.assertTrue(request.attendance_created)
        self.assertEqual(request.attendance_id.check_in, datetime(2026, 9, 23, 4, 30))
        self.assertEqual(request.attendance_id.check_out, datetime(2026, 9, 23, 12, 30))
        self.assertAlmostEqual(request.regularized_shift_hours, 7.0)

    def test_late_checkout_corrects_check_out_only(self):
        with freeze_time(OPEN_CYCLE):
            request = self._request(category='late_checkout', regularize_check_in=0.0)
            request.action_submit()
            self._approve(request)

        self.assertEqual(request.attendance_id, self.missed)
        # Recorded check-in 09:30 IST kept, check-out 18:00 IST.
        self.assertEqual(self.missed.check_in, datetime(2026, 9, 21, 4, 0))
        self.assertEqual(self.missed.check_out, datetime(2026, 9, 21, 12, 30))
        # 09:30-13:00 + 14:00-18:00
        self.assertAlmostEqual(request.regularized_shift_hours, 7.5)

        with freeze_time(OPEN_CYCLE):
            request.action_set_draft()
        self.assertEqual(self.missed.check_in, datetime(2026, 9, 21, 4, 0))
        self.assertEqual(self.missed.check_out, datetime(2026, 9, 21, 4, 0))

    def test_late_checkout_proposes_recorded_check_out(self):
        request = self.env['bxi.shift.exception'].new({
            'employee_id': self.employee.id,
            'category': 'late_checkout',
            'date_from': TUESDAY,
        })
        request._onchange_late_checkout_time()
        # Tuesday attendance checked out at 18:00 IST.
        self.assertAlmostEqual(request.regularize_check_out, 18.0)

        # Monday is a missed check-out: nothing to propose.
        request.regularize_check_out = 0.0
        request.date_from = MONDAY
        request._onchange_late_checkout_time()
        self.assertEqual(request.regularize_check_out, 0.0)

    def test_late_checkout_needs_recorded_check_in(self):
        request = self._request(day=WEDNESDAY, category='late_checkout', regularize_check_in=0.0)
        with freeze_time(OPEN_CYCLE), self.assertRaises(UserError):
            request.action_submit()

    def test_late_checkout_after_recorded_check_in(self):
        # Recorded check-in is 09:30 IST.
        request = self._request(
            category='late_checkout', regularize_check_in=0.0, regularize_check_out=9.0)
        with freeze_time(OPEN_CYCLE), self.assertRaises(UserError):
            request.action_submit()

    def test_approve_cancels_lop(self):
        self.env['hr.attendance']._create_missed_checkout_lwp(self.employee, MONDAY)
        self.assertTrue(self._lwp_leaves())

        with freeze_time(AFTER_CUTOFF), patch.object(
            type(self.env['res.users']), 'has_group', return_value=True,
        ):
            request = self._request()
            request.action_submit()
            self._approve(request)

        self.assertFalse(self._lwp_leaves())

    def test_set_draft_reverts_attendance_and_applies_lop_after_cutoff(self):
        with freeze_time(OPEN_CYCLE):
            request = self._request()
            request.action_submit()
            self._approve(request)
        with freeze_time(AFTER_CUTOFF):
            request.action_set_draft()

        self.assertEqual(self.missed.check_in, datetime(2026, 9, 21, 4, 0))
        self.assertEqual(self.missed.check_out, datetime(2026, 9, 21, 4, 0))
        self.assertFalse(self.missed.regularization_id)
        self.assertFalse(request.attendance_id)
        self.assertEqual(request.regularized_shift_hours, 0.0)
        self.assertTrue(self._lwp_leaves())

    def test_set_draft_removes_created_attendance(self):
        with freeze_time(OPEN_CYCLE):
            request = self._request(day=WEDNESDAY)
            request.action_submit()
            self._approve(request)
            attendance = request.attendance_id
            request.action_set_draft()

        self.assertFalse(attendance.exists())
        self.assertFalse(self._lwp_leaves(WEDNESDAY))

    def test_refuse_after_cutoff_applies_lop(self):
        with freeze_time(OPEN_CYCLE):
            request = self._request()
            request.action_submit()
        with freeze_time(AFTER_CUTOFF):
            request.action_refuse()
        self.assertTrue(self._lwp_leaves())

    def test_refuse_before_cutoff_no_lop(self):
        with freeze_time(OPEN_CYCLE):
            request = self._request()
            request.action_submit()
            request.action_refuse()
        self.assertFalse(self._lwp_leaves())

    # ------------------------------------------------------------
    # Crons
    # ------------------------------------------------------------

    def _summary_mails(self, model, res_id):
        return self.env['mail.mail'].search([
            ('model', '=', model),
            ('res_id', '=', res_id),
        ])

    def test_weekly_manager_and_hr_summaries(self):
        with freeze_time(OPEN_CYCLE):
            self._request(day=WEDNESDAY).action_submit()
            self.env['bxi.shift.exception']._cron_send_regularization_reminders()

        manager_mail = self._summary_mails('hr.employee', self.manager.id)
        self.assertEqual(len(manager_mail), 1)
        self.assertEqual(manager_mail.email_to, 'regularization.manager@example.com')
        self.assertIn('25-09-2026', manager_mail.subject)
        body = manager_mail.body_html
        self.assertIn('Regularization Employee', body)
        self.assertIn('21-09-2026', body)
        self.assertIn('23-09-2026', body)
        self.assertNotIn('22-09-2026', body)
        self.assertIn('No request', body)
        self.assertIn('Awaiting approval', body)

        hr_mail = self._summary_mails('res.company', self.company.id)
        self.assertEqual(len(hr_mail), 1)
        self.assertEqual(hr_mail.email_to, 'hrsupport@bxitech.com')
        self.assertIn('Regularization Employee', hr_mail.body_html)

        # Summaries only: nothing to the employee.
        self.assertFalse(self._summary_mails('hr.employee', self.employee.id))

    def test_no_summary_after_25th(self):
        with freeze_time(AFTER_CUTOFF):
            self.env['bxi.shift.exception']._cron_send_regularization_reminders()
        self.assertFalse(self._summary_mails('hr.employee', self.manager.id))
        self.assertFalse(self._summary_mails('res.company', self.company.id))

    def test_cutoff_cron_applies_silent_lop(self):
        with freeze_time(OPEN_CYCLE):
            approved = self._request(day=WEDNESDAY)
            approved.action_submit()
            self._approve(approved)
            # Pending at the cutoff: LOP as well.
            self._request().action_submit()

        with freeze_time(AFTER_CUTOFF), patch.object(
            type(self.env['hr.leave']), '_send_leave_submission_email',
        ) as submission_email:
            self.env['bxi.shift.exception']._cron_apply_regularization_lop()

        leave = self._lwp_leaves(MONDAY)
        self.assertEqual(len(leave), 1)
        self.assertEqual(leave.state, 'validate')
        self.assertEqual(self.missed.lwp_leave_id, leave)
        self.assertFalse(self._lwp_leaves(TUESDAY))
        self.assertFalse(self._lwp_leaves(WEDNESDAY))
        submission_email.assert_not_called()

    def test_late_approval_after_cutoff_cancels_lop(self):
        with freeze_time(OPEN_CYCLE):
            request = self._request()
            request.action_submit()
        with freeze_time(AFTER_CUTOFF):
            self.env['bxi.shift.exception']._cron_apply_regularization_lop()
            self.assertTrue(self._lwp_leaves())
            self._approve(request)
        self.assertEqual(request.state, 'approved')
        self.assertFalse(self._lwp_leaves())

    def test_approval_blocked_once_payroll_processed(self):
        if 'hr.payslip' not in self.env:
            self.skipTest('om_hr_payroll is not installed')
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'date_from': date(2026, 9, 1),
            'date_to': date(2026, 9, 30),
        })
        payslip.state = 'done'
        with freeze_time(OPEN_CYCLE):
            request = self._request()
            request.action_submit()
            with self.assertRaises(UserError):
                self._approve(request)
        self.assertEqual(request.state, 'manager_approval')

    # ------------------------------------------------------------
    # Timesheet gaps
    # ------------------------------------------------------------

    def _enable_timesheet_check(self):
        self.company.timesheet_check_start_date = MONDAY

    def test_timesheet_gap_disabled_before_start_date(self):
        self.company.timesheet_check_start_date = date(2026, 10, 26)
        self.assertEqual(self._gaps(), {MONDAY: {'attendance'}, WEDNESDAY: {'attendance'}})

    def test_timesheet_gaps(self):
        self._enable_timesheet_check()
        self._log_timesheet(WEDNESDAY)
        self.assertEqual(self._gaps(), {
            MONDAY: {'attendance', 'timesheet'},
            # Check-in and check-out, but no timesheet.
            TUESDAY: {'timesheet'},
            WEDNESDAY: {'attendance'},
        })

    def test_any_timesheet_state_counts(self):
        self._enable_timesheet_check()
        line = self._log_timesheet(TUESDAY)
        line.sudo().write({'state': 'refused'})
        self.assertNotIn(TUESDAY, self._gaps())

    def test_missing_timesheet_clears_only_timesheet_gap(self):
        self._enable_timesheet_check()
        with freeze_time(OPEN_CYCLE):
            request = self._request(category='missing_timesheet')
            request.action_submit()
            self._approve(request)
        self.assertEqual(self._gaps()[MONDAY], {'attendance'})

    def test_two_requests_for_both_gaps(self):
        self._enable_timesheet_check()
        with freeze_time(OPEN_CYCLE):
            attendance = self._request()
            attendance.action_submit()
            timesheet = self._request(category='missing_timesheet')
            timesheet.action_submit()
            with self.assertRaises(UserError):
                self._request(category='late_checkout').action_submit()
            self._approve(attendance)
            self._approve(timesheet)
        self.assertNotIn(MONDAY, self._gaps())

    def test_missing_timesheet_rejected_when_logged(self):
        self._enable_timesheet_check()
        self._log_timesheet(TUESDAY)
        request = self._request(day=TUESDAY, category='missing_timesheet')
        with freeze_time(OPEN_CYCLE), self.assertRaises(UserError):
            request.action_submit()

    def test_lop_cancelled_only_when_all_gaps_approved(self):
        self._enable_timesheet_check()
        self.env['hr.attendance']._create_missed_checkout_lwp(self.employee, MONDAY)
        with freeze_time(AFTER_CUTOFF), patch.object(
            type(self.env['res.users']), 'has_group', return_value=True,
        ):
            attendance = self._request()
            attendance.action_submit()
            self._approve(attendance)
            self.assertTrue(self._lwp_leaves())

            timesheet = self._request(category='missing_timesheet')
            timesheet.action_submit()
            self._approve(timesheet)
        self.assertFalse(self._lwp_leaves())

    def test_dashboard_absent_for_missing_timesheet(self):
        self._enable_timesheet_check()
        with freeze_time(OPEN_CYCLE):
            overrides = self._overrides()
            self.assertEqual(
                overrides[(self.employee.id, TUESDAY)], {'shift_prod': 0.0, 'status': 'absent'})

            request = self._request(day=TUESDAY, category='missing_timesheet')
            request.action_submit()
            self._approve(request)
            overrides = self._overrides()
        # Approved: the DeskTime hours count as they are.
        self.assertNotIn((self.employee.id, TUESDAY), overrides)

    def test_summary_lists_missing_timesheet(self):
        self._enable_timesheet_check()
        with freeze_time(OPEN_CYCLE):
            self.env['bxi.shift.exception']._cron_send_regularization_reminders()
        body = self._summary_mails('hr.employee', self.manager.id).body_html
        self.assertIn('22-09-2026', body)
        self.assertIn('Missing timesheet', body)

    # ------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------

    def _overrides(self):
        return self.env['bxi.timesheet.dashboard']._get_attendance_overrides(
            self.employee, MONDAY, date(2026, 9, 27),
        )

    def test_dashboard_absent_in_open_cycle(self):
        with freeze_time(OPEN_CYCLE):
            overrides = self._overrides()
        self.assertEqual(
            overrides[(self.employee.id, MONDAY)], {'shift_prod': 0.0, 'status': 'absent'})
        self.assertEqual(
            overrides[(self.employee.id, WEDNESDAY)], {'shift_prod': 0.0, 'status': 'absent'})
        self.assertNotIn((self.employee.id, TUESDAY), overrides)

    def test_dashboard_absent_until_approved(self):
        with freeze_time(OPEN_CYCLE):
            self._request().action_submit()
            overrides = self._overrides()
        self.assertEqual(
            overrides[(self.employee.id, MONDAY)], {'shift_prod': 0.0, 'status': 'absent'})

    def test_dashboard_lop_after_cutoff_while_pending(self):
        with freeze_time(OPEN_CYCLE):
            self._request().action_submit()
        with freeze_time(AFTER_CUTOFF):
            overrides = self._overrides()
        self.assertEqual(
            overrides[(self.employee.id, MONDAY)], {'shift_prod': 0.0, 'status': 'lop'})

    def test_dashboard_lop_after_cutoff(self):
        with freeze_time(AFTER_CUTOFF):
            self.env['bxi.shift.exception']._cron_apply_regularization_lop()
            overrides = self._overrides()
        self.assertEqual(
            overrides[(self.employee.id, MONDAY)], {'shift_prod': 0.0, 'status': 'lop'})

    def test_dashboard_counts_approved_hours(self):
        with freeze_time(OPEN_CYCLE):
            request = self._request()
            request.action_submit()
            self._approve(request)
            overrides = self._overrides()
        self.assertEqual(
            overrides[(self.employee.id, MONDAY)], {'shift_prod': 8.0, 'status': False})
