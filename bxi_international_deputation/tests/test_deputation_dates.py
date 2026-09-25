from datetime import date

from odoo.tests import BaseCase, tagged

from odoo.addons.bxi_international_deputation.models.deputation_dates import (
    CALENDAR, WORKING, compute_outbound, compute_return,
)


def mon_fri(day):
    return day.weekday() < 5


def sun_thu(day):
    return day.weekday() in (6, 0, 1, 2, 3)


# 2026-05-02 is a Saturday.
SAT = date(2026, 5, 2)
SUN = date(2026, 5, 3)
MON = date(2026, 5, 4)
WED = date(2026, 5, 6)
FRI = date(2026, 5, 8)


@tagged('post_install', '-at_install')
class TestDeputationDates(BaseCase):

    def test_working_days_outbound_saturday(self):
        """Policy: India -> UK on Saturday. India pays Saturday, Sunday is a gap day, UK from Monday."""
        home_last, host_start, gaps = compute_outbound(SAT, WORKING, mon_fri)
        self.assertEqual(home_last, SAT)
        self.assertEqual(host_start, MON)
        self.assertEqual(gaps, [SUN])

    def test_working_days_outbound_weekday(self):
        home_last, host_start, gaps = compute_outbound(WED, WORKING, mon_fri)
        self.assertEqual(home_last, date(2026, 5, 5))
        self.assertEqual(host_start, WED)
        self.assertEqual(gaps, [])

    def test_calendar_days_outbound_saturday(self):
        """Policy: to a Calendar Days country on Saturday, the host salary starts on Saturday."""
        home_last, host_start, gaps = compute_outbound(SAT, CALENDAR, mon_fri)
        self.assertEqual(home_last, date(2026, 5, 1))
        self.assertEqual(host_start, SAT)
        self.assertEqual(gaps, [])

    def test_working_days_return_sunday(self):
        """Policy: UK -> India on Sunday. UK pays until Friday, Saturday is a gap day, India from Sunday."""
        host_last, home_restart, gaps = compute_return(date(2026, 5, 10), WORKING, mon_fri)
        self.assertEqual(host_last, FRI)
        self.assertEqual(home_restart, date(2026, 5, 10))
        self.assertEqual(gaps, [date(2026, 5, 9)])

    def test_calendar_days_return(self):
        host_last, home_restart, gaps = compute_return(date(2026, 5, 10), CALENDAR, mon_fri)
        self.assertEqual(host_last, date(2026, 5, 9))
        self.assertEqual(home_restart, date(2026, 5, 10))
        self.assertEqual(gaps, [])

    def test_public_holiday_extends_gap(self):
        """Saturday arrival before a Monday public holiday: Sunday and Monday are gap days."""
        def uk_with_holiday(day):
            return mon_fri(day) and day != MON

        home_last, host_start, gaps = compute_outbound(SAT, WORKING, uk_with_holiday)
        self.assertEqual(host_start, date(2026, 5, 5))
        self.assertEqual(home_last, SAT)
        self.assertEqual(gaps, [SUN, MON])

    def test_friday_saturday_weekend(self):
        """Gulf countries: landing on Friday, the host payroll starts on Sunday."""
        home_last, host_start, gaps = compute_outbound(FRI, WORKING, sun_thu)
        self.assertEqual(home_last, FRI)
        self.assertEqual(host_start, date(2026, 5, 10))
        self.assertEqual(gaps, [date(2026, 5, 9)])
