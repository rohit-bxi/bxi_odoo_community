# BXI Employee Milestones

Three daily scheduled jobs (03:30 UTC = 09:00 IST), under Settings > Technical > Scheduled Actions:

| Job | Who it targets | Email |
|---|---|---|
| Happy Birthday Emails | Active employees whose `Birthday` is today | To the employee, Cc the reporting manager |
| Happy Job Anniversary Emails | Active employees whose `Date of Joining` (`emp_date_of_joining`) is today, 1+ years ago | To the employee, Cc the reporting manager and HR |
| Start Probation Reviews | Employees with `Probation Period = Yes` whose probation ends within 10 days (or has already ended) | To the reporting manager, Cc HR |

- A 29 February birthday or joining date is celebrated on 28 February in non-leap years.
- Each employee gets at most one birthday and one anniversary email per year, even if a job is run again by hand.
- Employees without a work email are skipped.
- "HR" is the **HR Email** in Settings > Employees > Employee Milestones (default `hrsupport@bxitech.com`).
- The email texts are the templates named "Employee Milestones: ..." in Settings > Technical > Email Templates.

## Probation confirmation

The probation end date is the date of joining + 6 months, shown on the employee form under
Probation Period. HR can change it to extend the probation.

1. **Waiting Manager**: the reporting manager gets an email and a to-do activity. They
   *Confirm Probation*, or *Do Not Confirm* with comments.
2. **Waiting HR**: on manager confirmation the HR email and the employee's HR Responsible
   (activity) are notified. HR (Employees: Officer or above) *HR Approve*s or *Do Not Confirm*s with comments.
3. **Confirmed**: the employee's Probation Period is set to No and the Confirmation Date to
   the probation end date.

When the probation is not confirmed, HR gets a to-do activity. To extend it, move the employee's Probation End
Date: a new review starts 10 days before the new date. *Send Back to Manager* restarts a review.

If the employee has no manager with a user account, HR can do the manager step.
Reviews are under Employees > Probation Reviews. Managers see only their direct reports.

## Before installing in production

The first run starts a review for **every** employee still flagged `Probation Period = Yes`
whose probation has already ended. Check that list first and clean up stale flags:

```python
env['hr.employee'].search([('probation_period', '=', 'yes')]).mapped(lambda e: (e.name, e.emp_date_of_joining))
```
