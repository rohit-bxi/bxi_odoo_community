from odoo import models, fields, api, _
from datetime import date


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
    def cron_allocate_el(self):

        today = date.today()

        # Ensure it runs only on 1st
        if today.day != 1:
            return

        el_type = self.env['hr.leave.type'].search([('time_off_code', '=', 'EL')], limit=1)
        if not el_type:
            return

        employees = self.search([('active', '=', True)])

        for emp in employees:

            if not emp.emp_date_of_joining:
                continue

            doj = emp.emp_date_of_joining
            days_since_doj = (today - doj).days

            # =========================================
            # FIRST MONTH LOGIC
            # =========================================
            if days_since_doj < 30:

                existing = self.env['hr.leave.allocation'].search([
                    ('employee_id', '=', emp.id),
                    ('holiday_status_id', '=', el_type.id),
                    ('name', '=', 'EL First Month Allocation')
                ], limit=1)

                if not existing:

                    if 1 <= doj.day <= 7:
                        allocation = 1.5
                    elif 8 <= doj.day <= 14:
                        allocation = 1.0
                    elif 15 <= doj.day <= 21:
                        allocation = 0.5
                    else:
                        allocation = 0

                    if allocation > 0:
                        record = self.env['hr.leave.allocation'].create({
                            'name': 'EL First Month Allocation',
                            'employee_id': emp.id,
                            'holiday_status_id': el_type.id,
                            'number_of_days': allocation,
                        })
                        record.action_approve()

            # =========================================
            # MONTHLY EL AFTER FIRST MONTH
            # =========================================
            else:

                month_key = today.strftime('%Y-%m')

                existing = self.env['hr.leave.allocation'].search([
                    ('employee_id', '=', emp.id),
                    ('holiday_status_id', '=', el_type.id),
                    ('name', '=', f'EL Monthly {month_key}')
                ], limit=1)

                if not existing:
                    record = self.env['hr.leave.allocation'].create({
                        'name': f'EL Monthly {month_key}',
                        'employee_id': emp.id,
                        'holiday_status_id': el_type.id,
                        'number_of_days': 1.5,
                    })
                    record.action_approve()