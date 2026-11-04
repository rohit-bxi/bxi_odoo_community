from odoo import models, fields, _
import base64
from odoo.exceptions import UserError
import io
import xlsxwriter
import openpyxl
from datetime import datetime, time
from odoo import Command

EXPECTED_HEADERS = [
    'EmployeeCode', 'EmployeeName', 'Company', 'Department', 'LastPunch',
    'Direction', 'PunchRecords', 'Status'
]


class ManualImport(models.TransientModel):
    _name = 'manual.upload.attendance'
    _description = 'Manual Upload Attendance'

    option_dropdown = fields.Selection([('update', 'Update'),('download', 'Download')], string="Options")
    upload_option = fields.Selection([('perticular_date', 'Perticular Date'),('in_between', 'In-Between')], string="Upload Options")
    record_uploaded_for_date = fields.Date()
    upload_file = fields.Binary()
    device_id = fields.Many2one('essl.api.config', string="Biometric Device",
                                help="Look the employee codes up on this device only. Needed when "
                                     "the same code is used on several devices.")

    def _read_rows(self):
        """Check the uploaded file has the expected format and return its data rows."""
        if not self.upload_file:
            raise UserError(_("No file uploaded. Please upload an XLSX file."))

        file_content = base64.b64decode(self.upload_file)

        if not file_content.startswith(b'PK'):
            raise UserError(_("The uploaded file is not a valid .xlsx file."))

        workbook = openpyxl.load_workbook(io.BytesIO(file_content), read_only=True, data_only=True)
        rows = workbook.active.iter_rows(values_only=True)

        uploaded_headers = [str(value).strip() if value is not None else "" for value in next(rows, ())]
        while uploaded_headers and not uploaded_headers[-1]:
            uploaded_headers.pop()

        if uploaded_headers != EXPECTED_HEADERS:
            raise UserError(_(
                "The uploaded file does not have the correct format.\n"
                "Expected Headers: {}\n"
                "Uploaded Headers: {}".format(", ".join(EXPECTED_HEADERS), ", ".join(uploaded_headers))
            ))

        return list(rows)

    def action_download_excel(self):
        output = io.BytesIO()

        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet('Attendance Records')
        headers = EXPECTED_HEADERS

        header_format = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#D3D3D3'})
        cell_format = workbook.add_format({'align': 'center'})

        column_widths = [len(header) for header in headers]
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)

        sample_data = [
            ['37','Rohit', 'Default', 'Default', '11:23', '','09:48,10:13,11:23,11:23', 'Present'],
            ['20','Rakshanda', 'Default', 'Default', '12:01', '','10:14,12:01', 'Present'],
        ]

        for row, data in enumerate(sample_data, start=1):
            for col, value in enumerate(data):
                cell_value = str(value) if not isinstance(value, str) else value
                worksheet.write(row, col, cell_value, cell_format)
                column_widths[col] = max(column_widths[col], len(cell_value))

        for col, width in enumerate(column_widths):
            worksheet.set_column(col, col, width + 2)

        workbook.close()
        output.seek(0)

        file_content = base64.b64encode(output.read())
        output.close()

        attachment = self.env['ir.attachment'].create({
            'name': 'sample_attendance_upload.xlsx',
            'datas': file_content,
            'type': 'binary',
            'res_model': self._name,
            'res_id': self.id,
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_confirm(self):
        self.ensure_one()
        if self.option_dropdown != 'update':
            return {'type': 'ir.actions.act_window_close'}
        rows = self._read_rows()
        if self.upload_option == 'in_between':
            raise UserError(_("In-Between upload is not supported yet. Please upload one file per date."))
        return self._import_for_date(rows)

    @staticmethod
    def _parse_time(value):
        """Excel gives a punch time as text ("09:48"), or as a time or datetime cell."""
        if isinstance(value, datetime):
            value = value.time()
        if isinstance(value, time):
            return value.replace(second=0, microsecond=0)
        value = str(value).strip()
        try:
            return datetime.strptime(value, "%H:%M").time()
        except ValueError:
            return datetime.strptime(value, "%H:%M:%S").time().replace(second=0)

    def _parse_punches(self, value):
        if isinstance(value, (datetime, time)):
            return [self._parse_time(value)]
        return [self._parse_time(part) for part in str(value).split(',') if part.strip()]

    def _import_for_date(self, rows):
        """Replace each listed employee's attendance of the chosen date with the file's punches.

        Nothing is imported if any row is invalid.
        """
        if not self.record_uploaded_for_date:
            raise UserError(_("Please select the date the file is for."))

        to_import = []
        errors = []
        for row_number, row in enumerate(rows, start=2):
            row = (tuple(row) + (None,) * len(EXPECTED_HEADERS))[:len(EXPECTED_HEADERS)]
            employee_code, employee_name, company, department, last_punch, direction, punch_records, status = row
            if not punch_records:
                # absent, or an empty line
                continue

            if isinstance(employee_code, float) and employee_code.is_integer():
                employee_code = int(employee_code)
            employee_code = str(employee_code).strip() if employee_code is not None else ""
            domain = [('essl_emp_code', '=', employee_code)]
            if self.device_id:
                domain.append(('device_id', '=', self.device_id.id))
            employee_id = self.env['hr.employee'].sudo().search(domain, limit=2)
            if not employee_code or not employee_id:
                errors.append(_("Row %(row)s: employee not found with code: %(code)s",
                                row=row_number, code=employee_code))
                continue
            if len(employee_id) > 1:
                errors.append(_("Row %(row)s: code %(code)s is used by several employees, "
                                "please select the Biometric Device.", row=row_number, code=employee_code))
                continue

            try:
                punch_times = self._parse_punches(punch_records)
                if last_punch:
                    punch_times.append(self._parse_time(last_punch))
            except ValueError:
                errors.append(_("Row %(row)s (%(name)s): invalid punch time, expected HH:MM.",
                                row=row_number, name=employee_name))
                continue
            to_import.append((employee_id, sorted(set(punch_times)), status))

        if errors:
            raise UserError(_("The file was not imported:\n%s", "\n".join(errors)))

        for employee_id, punch_times, status in to_import:
            self._replace_attendance(employee_id, punch_times, status)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': _("Attendance imported for %s employee(s).", len(to_import)),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def _replace_attendance(self, employee_id, punch_times, status):
        current_date = self.record_uploaded_for_date
        device = self.device_id or employee_id.device_id
        punch_times = [device._to_utc(datetime.combine(current_date, punch_time)) for punch_time in punch_times]
        day_begin, day_end = device._get_day_window(current_date)

        # Exported device punches, like the sync: bxi_attendance skips its GPS check.
        # Only Attendance Administrators can run this wizard.
        Attendance = self.env['hr.attendance'].sudo().with_context(essl_biometric_sync=True)
        # Same attendance as the device sync would pick; other attendances of the day are kept.
        get_attendance_id = Attendance.search([
            ('employee_id', '=', employee_id.id),
            ('check_in', '>=', day_begin),
            ('check_in', '<', day_end),
        ]).sorted(lambda att: (not att.synced_with_essl, att.check_in))[:1]

        attendance_data = {
            'check_in': punch_times[0],
            'check_out': punch_times[-1],
            'synced_with_essl': True,
            'essl_status': status,
            'essl_punch_history_ids': [Command.create({'punch_in_times': punch_time}) for punch_time in punch_times],
        }
        if get_attendance_id:
            get_attendance_id.essl_punch_history_ids.unlink()
            get_attendance_id.write(attendance_data)
        else:
            Attendance.create(dict(attendance_data, employee_id=employee_id.id, in_mode='manual'))
