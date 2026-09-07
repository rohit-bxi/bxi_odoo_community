from odoo import models, fields, api, _
from datetime import date, datetime, timedelta


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # Optional tracking fields (recommended for performance)
    emp_date_of_joining = fields.Date(string="Date Of Joining")

    # =========================================================
    # RH CRON (RUN DAILY)
    # =========================================================
    def cron_allocate_rh(self):

        today = date.today()

        rh_type = self.env['hr.leave.type'].search([('time_off_code', '=', 'RH')], limit=1)
        if not rh_type:
            return

        employees = self.search([('active', '=', True)])

        for emp in employees:
            if not emp.emp_date_of_joining:
                continue

            doj = emp.emp_date_of_joining
            days_since_doj = (today - doj).days

            # Total completed quarters
            completed_quarters = days_since_doj // 90

            if completed_quarters <= 0:
                continue

            # ============================
            # FETCH EXISTING RH ALLOCATIONS
            # ============================
            allocations = self.env['hr.leave.allocation'].search([
                ('employee_id', '=', emp.id),
                ('holiday_status_id', '=', rh_type.id),
                ('state', '=', 'validate')
            ])

            allocated_rh = sum(allocations.mapped('number_of_days'))

            # ============================
            # CALCULATE DIFFERENCE
            # ============================
            to_allocate = int(completed_quarters - allocated_rh)

            if to_allocate > 0:
                record = self.env['hr.leave.allocation'].create({
                    'name': f'RH Allocation ({completed_quarters * 3} Months)',
                    'employee_id': emp.id,
                    'holiday_status_id': rh_type.id,
                    'number_of_days': to_allocate,
                    # 'state': 'validate'
                })

                # record.action_confirm()
                record.action_approve()


    # =========================================================
    # EL CRON (RUN MONTHLY - 1ST DAY)
    # =========================================================
    @api.model
    def cron_allocate_el(self):

        today = date.today()

        # Cron should run only on the 1st day of the month
        if today.day != 1:
            return

        # ---------------------------------------------------------
        # Get Earned Leave type
        # ---------------------------------------------------------
        el_type = self.env['hr.leave.type'].search([
            ('time_off_code', '=', 'EL')
        ], limit=1)

        if not el_type:
            return

        # ---------------------------------------------------------
        # Previous month date range
        # ---------------------------------------------------------
        first_day_current_month = today.replace(day=1)
        last_day_previous_month = first_day_current_month - timedelta(days=1)
        first_day_previous_month = last_day_previous_month.replace(day=1)
        start_datetime = datetime.combine(
            first_day_previous_month,
            datetime.min.time()
        )

        end_datetime = datetime.combine(
            first_day_current_month,
            datetime.min.time()
        )

        employees = self.search([
            ('active', '=', True),
            ('work_email', '!=', False),
            ('emp_date_of_joining', '!=', False),
        ])

        for emp in employees:

            # -----------------------------------------------------
            # Find attendance using employee work email
            # -----------------------------------------------------
            attendances = self.env['hr.attendance'].search([
                ('employee_id.work_email', '=', emp.work_email),
                ('check_in', '>=', start_datetime),
                ('check_in', '<', end_datetime),
            ])

            # -----------------------------------------------------
            # Count UNIQUE attendance dates
            # -----------------------------------------------------
            attendance_dates = set()

            for attendance in attendances:
                if attendance.check_in:
                    attendance_date = attendance.check_in.date()
                    attendance_dates.add(attendance_date)

            attendance_days = len(attendance_dates)

            # -----------------------------------------------------
            # Check whether employee already received EL
            # for this attendance month
            # -----------------------------------------------------
            month_key = first_day_previous_month.strftime('%Y-%m')
            existing = self.env['hr.leave.allocation'].search([
                ('employee_id', '=', emp.id),
                ('holiday_status_id', '=', el_type.id),
                ('name', '=', f'EL Monthly {month_key}'),
            ], limit=1)

            if existing:
                continue
            # -----------------------------------------------------
            # → Allocate EL computed as 1.5 / (attendance_days + EL_applied_days_approved + RH_applied_days_approved)
            # No minimum attendance gate — allocation computed when denom > 0.
            # -----------------------------------------------------

            # Sum EL days already approved in the same month
            el_leaves = self.env['hr.leave'].search([
                ('employee_id', '=', emp.id),
                ('holiday_status_id', '=', el_type.id),
                ('state', '=', 'validate'),
                ('request_date_from', '<=', last_day_previous_month),
                ('request_date_to', '>=', first_day_previous_month),
            ])

            el_applied_days = 0.0
            for l in el_leaves:
                days = getattr(l, 'number_of_days', False)
                if days:
                    try:
                        el_applied_days += float(days)
                    except Exception:
                        pass
                else:
                    # compute overlap days inclusive
                    s = max(l.request_date_from, first_day_previous_month)
                    e = min(l.request_date_to, last_day_previous_month)
                    try:
                        el_applied_days += (e - s).days + 1
                    except Exception:
                        pass

            # Sum RH days already approved in the same month
            rh_type = self.env['hr.leave.type'].search([('time_off_code', '=', 'RH')], limit=1)
            rh_applied_days = 0.0
            if rh_type:
                rh_leaves = self.env['hr.leave'].search([
                    ('employee_id', '=', emp.id),
                    ('holiday_status_id', '=', rh_type.id),
                    ('state', '=', 'validate'),
                    ('request_date_from', '<=', last_day_previous_month),
                    ('request_date_to', '>=', first_day_previous_month),
                ])
                for l in rh_leaves:
                    days = getattr(l, 'number_of_days', False)
                    if days:
                        try:
                            rh_applied_days += float(days)
                        except Exception:
                            pass
                    else:
                        s = max(l.request_date_from, first_day_previous_month)
                        e = min(l.request_date_to, last_day_previous_month)
                        try:
                            rh_applied_days += (e - s).days + 1
                        except Exception:
                            pass

            denom = attendance_days + el_applied_days + rh_applied_days

            if denom and denom > 0:
                alloc_days = round(1.5 / float(denom), 3)

                allocation = self.env['hr.leave.allocation'].create({
                    'name': f'EL Monthly {month_key}',
                    'employee_id': emp.id,
                    'holiday_status_id': el_type.id,
                    'number_of_days': alloc_days,
                })

                allocation.action_approve()