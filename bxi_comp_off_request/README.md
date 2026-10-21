# BXI Comp-Off Requests — Odoo 19

## Workflow
1. Employee creates a separate Comp-Off request and selects:
   - Weekend Work Date (Saturday/Sunday)
   - Comp-Off Date (Monday-Friday)
2. Submit is allowed only when the weekend work date is at least 5 calendar days in the future.
3. Reporting Manager approves.
4. HR Time Off Manager approves.
5. After the weekend date has passed, HR verifies completed attendance records.
6. At least 8 recorded attendance hours are required. The module then creates and validates a one-day allocation against the existing Comp-Off Time Off Type.

No role-band field or configuration is required. This is a separate model (`hr.comp.off.request`) with its own list and form views. It does not add request fields to `hr.leave`.

## Install
1. Back up the database and install on staging first.
2. Copy `bxi_comp_off_request` into a directory included in `addons_path`.
3. Restart Odoo and update the Apps list.
4. Install **BXI Comp-Off Requests**.
5. Assign the **Comp-Off User** group to employees who should raise requests.
6. Assign **Comp-Off Manager** to users who need broad read/write access, and ensure the intended HR approvers have Odoo's **Time Off Administrator/Manager** group (`hr_holidays.group_hr_holidays_manager`).
7. Confirm the existing Comp-Off Time Off Type is configured for allocation-based leave and its identifying code/name is Comp-Off / COMP-OFF.

## Important implementation notes
- The five-day advance rule is measured in calendar days from today's date to the weekend work date.
- Attendance is checked by searching completed `hr.attendance` records whose check-in falls on the selected weekend date and summing check-in/check-out duration. Overnight shifts crossing midnight should be tested and may need company-specific timezone handling.
- The allocation API and approval settings can vary with custom Odoo 19 builds. Validate on staging before production.
- The module does not create artificial `hr.attendance` records on the weekday off; the validated leave allocation is the correct representation of a compensatory day off.
- The generated allocation is one day. Expiry, auto-consumption restrictions, and enforcing that the employee uses only the selected `comp_off_date` require additional company-specific policy decisions and are not included here.
