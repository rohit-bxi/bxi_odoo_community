import logging
from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import Command, _, fields, models
from odoo.addons.base.models.res_partner import _tz_get
from odoo.exceptions import UserError

from .hr_attendance import EMPLOYEE_CHECKIN_MODES

_logger = logging.getLogger(__name__)
try:
    from zk import ZK
except ImportError:
    ZK = None
    _logger.error("Please Install pyzk library.")

# The defaults keep the behaviour from before these settings existed: device clocks
# in IST, and a business day running 05:30 to 05:30 so that late-night punch-outs
# stay with the shift they belong to.
DEFAULT_TZ = 'Asia/Kolkata'
DEFAULT_DAY_START = 5.5
# pyzk socket timeouts, in seconds
ZK_TIMEOUT = 60
ZK_DOWNLOAD_TIMEOUT = 350


class ESSLAPIConfig(models.Model):
    _name = 'essl.api.config'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Biometric API Configuration'
    _rec_name = 'name_id'

    # Identifier
    name_id = fields.Char(string="Configuration Name/ID")
    essl_api_config_ids = fields.One2many('visitors.detail', 'essl_id',
                                          help='Store Visitors Deatils of '
                                               'an employee')

    # Device Configuration
    device_name = fields.Char(string="Device Name")
    device_ip = fields.Char(string="Device IP", required=True)
    port_number = fields.Integer(string="Port Number", default=4370)
    device_password = fields.Char(string="Device Password",
                                  groups="hr_attendance.group_hr_attendance_manager")  # Optional
    tz = fields.Selection(_tz_get, string="Device Timezone", required=True, default=DEFAULT_TZ,
                          help="Timezone of the device clock. Punches are converted from it to UTC.")
    day_start_time = fields.Float(string="Day Starts At", default=DEFAULT_DAY_START,
                                  help="Punches before this time count towards the previous day, "
                                       "so late-night punch-outs stay with their shift.")
    company_id = fields.Many2one('res.company', string="Company", default=lambda self: self.env.company)
    work_location_id = fields.Many2one('hr.work.location', string="Location", tracking=True,
                                       domain="[('company_id', 'in', [company_id, False])]",
                                       help="Work location where the device is installed. The scheduled "
                                            "download reads the devices location by location.")
    is_live_capture = fields.Boolean(string="Live Capture", default=False)
    stopwatch_time = fields.Float(string="Elapsed Time", readonly=True)
    live_capture_start_time = fields.Datetime(string="Capture Start Time", readonly=True)
    device_firmware = fields.Char(string="Firmware", readonly=True)
    device_serial_no = fields.Char(string="Serial No.", readonly=True)
    device_platform = fields.Char(string="Platform", readonly=True)
    device_mac = fields.Char(string="MAC Address", readonly=True)
    status = fields.Selection([
        ('draft', 'Draft'),
        ('lock', 'Locked')
    ], string='Status', default='draft')
    start_date = fields.Date(string="Sync From",
                             help="Punches from this day on are read at the next download. It moves "
                                  "forward after each download, but stays on the first day that "
                                  "could not be synced so that day is retried.")

    def action_lock(self):
        for record in self:
            record.status = 'lock'
            for data in record.essl_api_config_ids.filtered('employee_id'):
                data.employee_id.sudo().write({
                    'essl_emp_code': data.visitors_id,
                    'device_id': record.id,
                })
            record.company_id.sudo().device_id = record

    def action_move_to_draft(self):
        for record in self:
            record.status = 'draft'

    def _zk_connect(self, timeout=ZK_TIMEOUT):
        """Connect to the device; the caller must disconnect the returned connection."""
        self.ensure_one()
        if ZK is None:
            raise UserError(_("Pyzk module not Found. Please install it with 'pip3 install pyzk'."))
        zk = ZK(self.device_ip, port=self.port_number, timeout=timeout,
                password=self.device_password or 0, force_udp=False, ommit_ping=False)
        try:
            return zk.connect()
        except Exception as error:
            raise UserError(_("Could not connect to the biometric device %(ip)s:%(port)s: %(error)s",
                              ip=self.device_ip, port=self.port_number, error=error)) from error

    def action_test_connection(self):
        self.ensure_one()
        conn = self._zk_connect()
        try:
            self.write({
                'device_name': conn.get_device_name(),
                'device_firmware': conn.get_firmware_version(),
                'device_serial_no': conn.get_serialnumber(),
                'device_platform': conn.get_platform(),
                'device_mac': conn.get_mac(),
            })
            conn.test_voice(index=0)
        except Exception as error:
            raise UserError(_("The biometric device did not answer: %s", error)) from error
        finally:
            conn.disconnect()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': 'BioMatric Device Successfully Connected',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def get_all_visitors(self):
        for config in self:
            conn = config._zk_connect()
            try:
                users = conn.get_users()
            finally:
                conn.disconnect()
            # Match on the device user ID only, so a renamed device user is updated
            # instead of being added a second time.
            visitors = {visitor.visitors_id: visitor for visitor in config.essl_api_config_ids}
            for user in users:
                visitor = visitors.get(user.user_id)
                if not visitor:
                    self.env['visitors.detail'].create({
                        'visitors_id': user.user_id,
                        'visitors_name': user.name,
                        'company_id': config.company_id.id,
                        'essl_id': config.id,
                    })
                elif visitor.visitors_name != user.name:
                    visitor.visitors_name = user.name

    def action_download_attendance(self, called_via_cron=False, location_ids=None):
        if called_via_cron:
            self._cron_download_attendance(location_ids)
            return

        logs = self.env['essl.attendance.sync.log']
        for config in self:
            logs |= config._download_attendance()
        if any(log.status == 'exception' for log in logs):
            message, notification_type = _("Some attendance could not be synced. "
                                           "Check the Biometric Attendance Sync Log."), 'warning'
        else:
            message, notification_type = _("Attendance downloaded from the biometric device."), 'success'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': message,
                'type': notification_type,
                'sticky': notification_type == 'warning',
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def _cron_download_attendance(self, location_ids=None):
        """Download the devices location by location; a failing device does not stop the others.

        :param location_ids: hr.work.location ids, to download only the devices of these
            locations (e.g. from a scheduled action of their own); all devices when not given
        """
        domain = [('work_location_id', 'in', location_ids)] if location_ids else []
        configs = self.sudo().search(domain, order='work_location_id, id')
        for location, location_configs in configs.grouped('work_location_id').items():
            _logger.info("Biometric attendance download for location %s: %s device(s)",
                         location.name or _("None"), len(location_configs))
            for config in location_configs:
                try:
                    with self.env.cr.savepoint():
                        config._download_attendance()
                except Exception as error:
                    # a UserError is an expected failure (device offline, nothing linked): no traceback
                    _logger.warning("Biometric attendance download failed for %s: %s", config._get_label(), error,
                                    exc_info=not isinstance(error, UserError))
                    self.env['essl.attendance.sync.log'].sudo().create({
                        'request_data': config.start_date,
                        'company_id': config.company_id.id,
                        'device_id': config.id,
                        'work_location_id': config.work_location_id.id,
                        'status': 'exception',
                        'exception_reason': str(error),
                    })

    def _get_label(self):
        return self.name_id or self.device_ip

    def _download_attendance(self):
        """Read the punches of this device from ``start_date`` on into hr.attendance.

        :return: the essl.attendance.sync.log of this run
        """
        self.ensure_one()
        if not self.start_date:
            raise UserError(_("Please set the Sync From date on %s.", self._get_label()))
        employees = self.env['hr.employee'].sudo().search([
            ('device_id', '=', self.id),
            ('essl_emp_code', '!=', False),
        ])
        if not employees:
            raise UserError(_("No employees are linked to %s. Get the visitors, map them to "
                              "employees and lock the configuration.", self._get_label()))
        employee_by_code = {employee.essl_emp_code: employee for employee in employees}

        conn = self._zk_connect(timeout=ZK_DOWNLOAD_TIMEOUT)
        try:
            device_punches = conn.get_attendance() or []
        finally:
            conn.disconnect()

        punches = defaultdict(list)
        for punch in device_punches:
            employee = employee_by_code.get(str(punch.user_id))
            punch_date = self._get_business_date(punch.timestamp)
            if employee and punch_date >= self.start_date:
                punches[employee, punch_date].append(punch.timestamp)
        return self._update_attendances(punches)

    def _update_attendances(self, punches):
        """Write the punches, one savepoint per employee and day, and log the run.

        :param punches: {(hr.employee, business date): [device-local punch datetimes]}
        """
        self.ensure_one()
        today = self._get_business_date(datetime.now(pytz.timezone(self.tz or DEFAULT_TZ)).replace(tzinfo=None))
        groups = sorted(punches.items(), key=lambda item: (item[0][1], item[0][0].id))
        log = self.env['essl.attendance.sync.log'].sudo().create({
            'request_data': self.start_date,
            'response_data': "\n".join(
                "%s %s | %s | %s" % (employee.essl_emp_code, employee.name, punch_date,
                                     ", ".join(t.strftime("%H:%M:%S") for t in sorted(times)))
                for (employee, punch_date), times in groups
            ) or _("No punches found."),
            'company_id': self.company_id.id,
            'device_id': self.id,
            'work_location_id': self.work_location_id.id,
            'status': 'draft',
        })
        errors = []
        failed_dates = []
        for (employee, punch_date), times in groups:
            try:
                with self.env.cr.savepoint():
                    self._create_update_attendance(employee, punch_date, times, today)
            except Exception as error:
                _logger.warning("Biometric attendance of %s on %s not synced: %s", employee.name, punch_date, error)
                errors.append("%s (%s): %s" % (employee.name, punch_date, error))
                failed_dates.append(punch_date)
        if errors:
            log.write({'status': 'exception', 'exception_reason': "\n".join(errors)})
        else:
            log.write({'status': 'done'})
        # Days before the first failure are final; the next run starts again from there.
        self.sudo().start_date = min(failed_dates, default=max(today, self.start_date))
        return log

    def _create_update_attendance(self, employee, punch_date, local_times, today):
        """Merge one employee's punches of one business day into a single attendance.

        The earliest punch is the check in and the latest the check out; an
        attendance the employee checked in to themselves is only extended. Other
        attendances of that day are left untouched.
        """
        # essl_biometric_sync: bxi_attendance skips its GPS check for device punches
        Attendance = self.env['hr.attendance'].sudo().with_context(essl_biometric_sync=True)
        punch_times = sorted({self._to_utc(local_time) for local_time in local_times})
        day_begin, day_end = self._get_day_window(punch_date)
        attendance = Attendance.search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', day_begin),
            ('check_in', '<', day_end),
        ]).sorted(lambda att: (not att.synced_with_essl, att.check_in))[:1]

        known_times = set(attendance.essl_punch_history_ids.mapped('punch_in_times'))
        new_times = [punch_time for punch_time in punch_times if punch_time not in known_times]
        day_is_over = punch_date < today
        if attendance.synced_with_essl and not new_times:
            # Nothing new: keep manual corrections, but close a missing punch-out once
            # the day is over, otherwise the open attendance blocks the next days.
            if day_is_over and not attendance.check_out:
                attendance.check_out = max(known_times | {attendance.check_in})
            return attendance

        all_times = sorted(known_times.union(new_times))
        if attendance.in_mode in EMPLOYEE_CHECKIN_MODES:
            # Checked in from the systray or kiosk (e.g. on an exception day): device
            # punches extend that attendance and never cut it short. While the day
            # lasts an open one stays open, the employee checks out themselves.
            check_in = min(attendance.check_in, all_times[0])
            if attendance.check_out:
                check_out = max(attendance.check_out, all_times[-1])
            else:
                check_out = all_times[-1] if day_is_over else False
        else:
            check_in = all_times[0]
            if len(all_times) > 1:
                check_out = all_times[-1]
            elif attendance.check_out and attendance.check_out > check_in:
                check_out = attendance.check_out
            else:
                check_out = check_in if day_is_over else False
        vals = {
            'check_in': check_in,
            'check_out': check_out,
            'synced_with_essl': True,
            'essl_punch_history_ids': [Command.create({'punch_in_times': punch_time}) for punch_time in new_times],
        }
        if attendance:
            attendance.write(vals)
            return attendance
        return Attendance.create(dict(vals, employee_id=employee.id, in_mode='manual'))

    # The helpers below also work on an empty recordset (an employee without a
    # device), falling back to the defaults.

    def _day_offset(self):
        return timedelta(hours=self.day_start_time if self else DEFAULT_DAY_START)

    def _to_utc(self, local_dt):
        """Convert a naive device-local datetime to a naive UTC one."""
        tz = pytz.timezone(self.tz or DEFAULT_TZ)
        return tz.localize(local_dt).astimezone(pytz.utc).replace(tzinfo=None)

    def _get_business_date(self, local_dt):
        """Return the business day a naive device-local datetime belongs to."""
        return (local_dt - self._day_offset()).date()

    def _get_day_window(self, day):
        """Return the naive UTC bounds [begin, end) of a business day."""
        offset = self._day_offset()
        return (self._to_utc(datetime.combine(day, time.min) + offset),
                self._to_utc(datetime.combine(day + timedelta(days=1), time.min) + offset))


class VisitorsDetails(models.Model):
    _name = 'visitors.detail'
    _description = 'Visitors Details'

    visitors_id = fields.Char(string='Visitor Biometric ID')
    visitors_name = fields.Char(string='Visitor Name(As per Biometric)')
    employee_id = fields.Many2one('hr.employee',string="Employee")
    company_id = fields.Many2one('res.company', string="Company", default=lambda self: self.env.company)
    essl_id = fields.Many2one('essl.api.config', ondelete='cascade')
