# -*- coding: utf-8 -*-
from datetime import date, datetime

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDesktimeShiftTimes(TransactionCase):
    """Shift based arrived/left and shift wise hours on DeskTime logs.

    Schedule: Monday 09:00-13:00, lunch 13:00-14:00, 14:00-18:00 (Asia/Kolkata, UTC+5:30).
    The lunch break is not counted in the shift wise hours.
    All datetimes below are stored UTC values.
    """

    MONDAY = date(2026, 9, 28)
    SUNDAY = date(2026, 9, 27)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'IST 9-6',
            'tz': 'Asia/Kolkata',
            'attendance_ids': [
                (5, 0, 0),
                (0, 0, {'name': 'Mon Morning', 'dayofweek': '0', 'hour_from': 9, 'hour_to': 13, 'day_period': 'morning'}),
                (0, 0, {'name': 'Mon Break', 'dayofweek': '0', 'hour_from': 13, 'hour_to': 14, 'day_period': 'lunch'}),
                (0, 0, {'name': 'Mon Afternoon', 'dayofweek': '0', 'hour_from': 14, 'hour_to': 18, 'day_period': 'afternoon'}),
            ],
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Shift Employee',
            'resource_calendar_id': cls.calendar.id,
        })

    def _log(self, arrived, left, log_date=MONDAY, employee=None):
        return self.env['bxi.desktime.log'].create({
            'employee_id': (employee or self.employee).id,
            'date': log_date,
            'arrived': arrived,
            'left': left,
        })

    def test_early_arrival_and_late_leave_clamped_to_shift(self):
        # 08:00 -> 19:30 IST
        log = self._log(datetime(2026, 9, 28, 2, 30), datetime(2026, 9, 28, 14, 0))
        self.assertEqual(log.shift_arrived, datetime(2026, 9, 28, 3, 30))  # 09:00 IST
        self.assertEqual(log.shift_left, datetime(2026, 9, 28, 12, 30))  # 18:00 IST
        self.assertAlmostEqual(log.shift_productive_hours, 8.0, places=2)  # lunch excluded

    def test_inside_shift_keeps_actual_times_and_excludes_break(self):
        # 09:40 -> 17:00 IST: 7h20 minus the 1h lunch break
        log = self._log(datetime(2026, 9, 28, 4, 10), datetime(2026, 9, 28, 11, 30))
        self.assertEqual(log.shift_arrived, log.arrived)
        self.assertEqual(log.shift_left, log.left)
        self.assertAlmostEqual(log.shift_productive_hours, 6 + 20 / 60, places=2)

    def test_no_left_time(self):
        log = self._log(datetime(2026, 9, 28, 2, 30), False)
        self.assertEqual(log.shift_arrived, datetime(2026, 9, 28, 3, 30))
        self.assertFalse(log.shift_left)
        self.assertEqual(log.shift_productive_hours, 0.0)

    def test_presence_outside_shift_window(self):
        # 18:30 -> 20:00 IST, after the shift ended
        log = self._log(datetime(2026, 9, 28, 13, 0), datetime(2026, 9, 28, 14, 30))
        self.assertFalse(log.shift_arrived)
        self.assertFalse(log.shift_left)
        self.assertEqual(log.shift_productive_hours, 0.0)

    def test_week_off(self):
        log = self._log(datetime(2026, 9, 27, 3, 30), datetime(2026, 9, 27, 12, 30), log_date=self.SUNDAY)
        self.assertFalse(log.shift_arrived)
        self.assertFalse(log.shift_left)
        self.assertEqual(log.shift_productive_hours, 0.0)

    def test_employee_without_schedule(self):
        employee = self.env['hr.employee'].create({'name': 'No Schedule'})
        employee.resource_calendar_id = False
        log = self._log(datetime(2026, 9, 28, 2, 30), datetime(2026, 9, 28, 14, 0), employee=employee)
        self.assertFalse(log.shift_arrived)
        self.assertFalse(log.shift_left)
        self.assertEqual(log.shift_productive_hours, 0.0)

    def test_schedule_change_keeps_old_logs(self):
        log = self._log(datetime(2026, 9, 28, 2, 30), datetime(2026, 9, 28, 14, 0))
        log.flush_recordset()  # values are stored at sync time, before any schedule change
        self.calendar.attendance_ids.filtered(lambda a: a.day_period == 'morning').hour_from = 10
        self.employee.resource_calendar_id = self.env['resource.calendar'].create({'name': 'Other', 'tz': 'UTC'})
        self.assertEqual(log.shift_arrived, datetime(2026, 9, 28, 3, 30))
        self.assertAlmostEqual(log.shift_productive_hours, 8.0, places=2)

    def test_resync_recomputes(self):
        log = self._log(datetime(2026, 9, 28, 2, 30), datetime(2026, 9, 28, 14, 0))
        log.write({'left': datetime(2026, 9, 28, 11, 30)})  # left at 17:00 IST
        self.assertEqual(log.shift_left, datetime(2026, 9, 28, 11, 30))
        self.assertAlmostEqual(log.shift_productive_hours, 7.0, places=2)

    def test_recalculate_action_uses_current_schedule(self):
        log = self._log(datetime(2026, 9, 28, 2, 30), datetime(2026, 9, 28, 14, 0))
        log.flush_recordset()
        # Shift now starts at 10:00 IST
        self.calendar.attendance_ids.filtered(lambda a: a.day_period == 'morning').hour_from = 10
        self.assertEqual(log.shift_arrived, datetime(2026, 9, 28, 3, 30))  # unchanged until recalculated

        log.action_recompute_shift_times()
        self.assertEqual(log.shift_arrived, datetime(2026, 9, 28, 4, 30))  # 10:00 IST
        self.assertAlmostEqual(log.shift_productive_hours, 7.0, places=2)

    def test_presence_during_lunch_only(self):
        # 13:10 -> 13:50 IST, entirely inside the lunch break
        log = self._log(datetime(2026, 9, 28, 7, 40), datetime(2026, 9, 28, 8, 20))
        self.assertEqual(log.shift_arrived, log.arrived)
        self.assertEqual(log.shift_left, log.left)
        self.assertEqual(log.shift_productive_hours, 0.0)
