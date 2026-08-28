# -*- coding: utf-8 -*-
import io
import base64
import calendar as py_calendar
from datetime import date, datetime, timedelta
import pytz
import xlsxwriter

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class BxiMonthlyAttendanceTimesheetWizard(models.TransientModel):
    _name = 'bxi.monthly.attendance.timesheet.wizard'
    _description = 'Monthly Attendance / Timesheet Report Wizard'

    def _get_year_selection(self):
        current_year = date.today().year
        return [(str(y), str(y)) for y in range(current_year - 5, current_year + 6)]

    month = fields.Selection([
        ('1', 'January'),
        ('2', 'February'),
        ('3', 'March'),
        ('4', 'April'),
        ('5', 'May'),
        ('6', 'June'),
        ('7', 'July'),
        ('8', 'August'),
        ('9', 'September'),
        ('10', 'October'),
        ('11', 'November'),
        ('12', 'December'),
    ], string='Month', required=True, default=lambda self: str(date.today().month))

    year = fields.Selection(
        selection=_get_year_selection,
        string='Year',
        required=True,
        default=lambda self: str(date.today().year)
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company
    )

    def action_generate_report(self):
        """Generate and download Monthly Attendance/Timesheet Report Excel sheet."""
        self.ensure_one()

        month_int = int(self.month)
        year_int = int(self.year)
        month_name = dict(self._fields['month'].selection).get(self.month, self.month)

        _, num_days = py_calendar.monthrange(year_int, month_int)
        start_date = date(year_int, month_int, 1)
        end_date = date(year_int, month_int, num_days)

        # 1. Fetch employees belonging to the selected company
        employees = self.env['hr.employee'].sudo().search([
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
        ], order='name asc')

        if not employees:
            raise UserError(_("No active employees found for %s.") % self.company_id.name)

        # 2. Timezone resolution for attendance check_in conversion
        user_tz_str = self.env.user.tz or 'Asia/Kolkata'
        try:
            user_tz = pytz.timezone(user_tz_str)
        except Exception:
            user_tz = pytz.timezone('Asia/Kolkata')

        # 3. Batch fetch attendances
        start_dt_utc = datetime.combine(start_date - timedelta(days=1), datetime.min.time())
        end_dt_utc = datetime.combine(end_date + timedelta(days=1), datetime.max.time())
        attendances = self.env['hr.attendance'].sudo().search([
            ('employee_id', 'in', employees.ids),
            ('check_in', '>=', start_dt_utc),
            ('check_in', '<=', end_dt_utc),
        ])
        emp_att_dates = set()
        for att in attendances:
            if att.check_in:
                local_in_date = pytz.utc.localize(att.check_in).astimezone(user_tz).date()
                if start_date <= local_in_date <= end_date:
                    emp_att_dates.add((att.employee_id.id, local_in_date))

        # 4. Batch fetch timesheets (including draft, submitted for approval, and approved)
        ts_domain = [
            ('employee_id', 'in', employees.ids),
            ('date', '>=', start_date),
            ('date', '<=', end_date),
            ('unit_amount', '>', 0.0),
        ]
        if 'state' in self.env['account.analytic.line']._fields:
            ts_domain.append(('state', '!=', 'refused'))
        ts_lines = self.env['account.analytic.line'].sudo().search(ts_domain)
        emp_ts_dates = set()
        emp_holiday_ts_dates = set()
        for ts in ts_lines:
            if hasattr(ts, 'holiday_id') and ts.holiday_id:
                emp_holiday_ts_dates.add((ts.employee_id.id, ts.date))
            else:
                emp_ts_dates.add((ts.employee_id.id, ts.date))

        # 5. Batch fetch leaves (including submitted / pending approval and approved leaves)
        leave_domain = [
            ('employee_id', 'in', employees.ids),
            ('request_date_from', '<=', end_date),
            ('request_date_to', '>=', start_date),
            ('state', 'not in', ['refuse', 'cancel']),
        ]
        leaves = self.env['hr.leave'].sudo().search(leave_domain)
        emp_leave_dates = set()
        for leave in leaves:
            l_start = max(leave.request_date_from, start_date)
            l_end = min(leave.request_date_to, end_date)
            curr = l_start
            while curr <= l_end:
                emp_leave_dates.add((leave.employee_id.id, curr))
                curr += timedelta(days=1)

        # 6. Build Excel Workbook with xlsxwriter
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet_name = f"{month_name[:3]}_{year_int}"
        sheet = workbook.add_worksheet(sheet_name)
        sheet.hide_gridlines(0)  # Show gridlines explicitly

        # Styles matching format
        header_format = workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#F4B084',  # Peach / Orange header color
            'font_color': '#000000',
            'border': 1,
            'font_name': 'Calibri',
            'font_size': 11,
        })

        sub_header_format = workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#F4B084',
            'font_color': '#000000',
            'border': 1,
            'font_name': 'Calibri',
            'font_size': 10,
        })

        cell_left_format = workbook.add_format({
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
            'font_name': 'Calibri',
            'font_size': 10,
        })

        cell_center_format = workbook.add_format({
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_name': 'Calibri',
            'font_size': 10,
        })

        # Set row heights
        sheet.set_row(0, 26)
        sheet.set_row(1, 22)

        # Top-level headers (Row 0 & 1 merged for Employee Name & Shift)
        sheet.merge_range(0, 0, 1, 0, 'Employee Name', header_format)
        sheet.merge_range(0, 1, 1, 1, 'Shift', header_format)

        # Day column headers
        dates_list = []
        for i in range(num_days):
            d = start_date + timedelta(days=i)
            dates_list.append(d)
            # Format date like: 1-Aug-26, 2-Aug-26 ...
            date_label = f"{d.day}-{d.strftime('%b')}-{d.strftime('%y')}"
            start_col = 2 + (i * 3)
            end_col = start_col + 2

            sheet.merge_range(0, start_col, 0, end_col, date_label, header_format)
            sheet.write(1, start_col, 'Attendance', sub_header_format)
            sheet.write(1, start_col + 1, 'Timesheet', sub_header_format)
            sheet.write(1, start_col + 2, 'Leave', sub_header_format)

        # Helper to test if a date is a Week-Off for the employee
        def is_employee_week_off(emp, target_date):
            calendar = emp.resource_calendar_id
            if not calendar:
                return target_date.weekday() >= 5  # Default Sat/Sun off
            day_str = str(target_date.weekday())
            day_atts = calendar.attendance_ids.filtered(lambda a: a.dayofweek == day_str)
            if 'date_from' in day_atts._fields:
                day_atts = day_atts.filtered(
                    lambda a: (not a.date_from or a.date_from <= target_date) and (not a.date_to or a.date_to >= target_date)
                )
            return len(day_atts) == 0

        # Fill Data Rows
        for row_idx, emp in enumerate(employees, start=2):
            sheet.set_row(row_idx, 20)
            sheet.write(row_idx, 0, emp.name, cell_left_format)
            shift_name = emp.resource_calendar_id.name if emp.resource_calendar_id else 'Working Schedule Name'
            sheet.write(row_idx, 1, shift_name, cell_left_format)

            for i, d in enumerate(dates_list):
                col_att = 2 + (i * 3)
                col_ts = col_att + 1
                col_lv = col_att + 2

                if is_employee_week_off(emp, d):
                    att_val = 'Week-Off'
                    ts_val = 'Week-Off'
                    lv_val = 'Week-Off'
                else:
                    att_val = 'Yes' if (emp.id, d) in emp_att_dates else 'No'
                    ts_val = 'Yes' if (emp.id, d) in emp_ts_dates else 'No'
                    lv_val = 'Yes' if ((emp.id, d) in emp_leave_dates or (emp.id, d) in emp_holiday_ts_dates) else 'No'

                sheet.write(row_idx, col_att, att_val, cell_center_format)
                sheet.write(row_idx, col_ts, ts_val, cell_center_format)
                sheet.write(row_idx, col_lv, lv_val, cell_center_format)

        # Set column widths
        sheet.set_column(0, 0, 24)  # Employee Name
        sheet.set_column(1, 1, 26)  # Shift
        total_data_cols = num_days * 3
        sheet.set_column(2, 2 + total_data_cols - 1, 12)  # Data sub-columns

        workbook.close()
        output.seek(0)

        # 7. Create temporary attachment for immediate download
        report_filename = f"Monthly_Attendance_Timesheet_Report_{month_name}_{year_int}.xlsx"
        attachment = self.env['ir.attachment'].sudo().create({
            'name': report_filename,
            'type': 'binary',
            'datas': base64.b64encode(output.getvalue()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
