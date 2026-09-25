"""Pure date rules of the International Deputation - Salary Processing Policy.

Kept free of the ORM so the policy examples can be unit-tested directly.
``is_working_day`` is a callable ``date -> bool`` for the host country.
"""
from datetime import timedelta

CALENDAR = 'calendar'
WORKING = 'working'

# Safety net against a host calendar with no working day at all.
MAX_SEARCH_DAYS = 60


def _days_between(first, last):
    """Dates strictly after ``first`` and strictly before ``last``."""
    days = []
    current = first + timedelta(days=1)
    while current < last:
        days.append(current)
        current += timedelta(days=1)
    return days


def _first_working_day_on_or_after(day, is_working_day):
    for offset in range(MAX_SEARCH_DAYS):
        candidate = day + timedelta(days=offset)
        if is_working_day(candidate):
            return candidate
    raise ValueError('No working day found within %s days after %s' % (MAX_SEARCH_DAYS, day))


def _last_working_day_before(day, is_working_day):
    for offset in range(1, MAX_SEARCH_DAYS + 1):
        candidate = day - timedelta(days=offset)
        if is_working_day(candidate):
            return candidate
    raise ValueError('No working day found within %s days before %s' % (MAX_SEARCH_DAYS, day))


def compute_outbound(arrival_date, approach, is_working_day):
    """Transfer from the home (India) payroll to the host payroll.

    Calendar Days approach: the host payroll starts on the arrival date and
    the home payroll ends the day before; there is no gap.

    Working Days approach: the host payroll starts on the first host working
    day on or after arrival. The home payroll pays up to the arrival date (or
    the day before the host start, if earlier). The days in between are gap
    days, paid by the host as a one-time ex-gratia.
    Policy example: India -> UK on Saturday: India pays Saturday, Sunday is a
    gap day, the UK payroll starts on Monday.

    :return: (home_last_date, host_start_date, [gap dates])
    """
    if approach == WORKING:
        host_start = _first_working_day_on_or_after(arrival_date, is_working_day)
        home_last = min(arrival_date, host_start - timedelta(days=1))
    else:
        host_start = arrival_date
        home_last = arrival_date - timedelta(days=1)
    return home_last, host_start, _days_between(home_last, host_start)


def compute_return(landing_date, approach, is_working_day):
    """Transfer from the host payroll back to the home (India) payroll.

    The home payroll restarts on the landing date in India.

    Calendar Days approach: the host payroll ends the day before landing.

    Working Days approach: the host payroll ends on the last host working day
    before landing; the days in between are gap days paid by the host in the
    final settlement.
    Policy example: UK -> India on Sunday: the UK pays until Friday, Saturday
    is a gap day, the India payroll starts on Sunday.

    :return: (host_last_date, home_restart_date, [gap dates])
    """
    if approach == WORKING:
        host_last = _last_working_day_before(landing_date, is_working_day)
    else:
        host_last = landing_date - timedelta(days=1)
    return host_last, landing_date, _days_between(host_last, landing_date)
