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
            # Attendance >= 15 days
            # → Allocate 1.5 EL
            # Attendance < 15 days
            # → No allocation
            # -----------------------------------------------------
            if attendance_days >= 15:

                allocation = self.env['hr.leave.allocation'].create({
                    'name': f'EL Monthly {month_key}',
                    'employee_id': emp.id,
                    'holiday_status_id': el_type.id,
                    'number_of_days': 1.5,
                })

                allocation.action_approve()