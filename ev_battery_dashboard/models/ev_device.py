# -*- coding: utf-8 -*-

from odoo import models, fields, api, _


class EvDevice(models.Model):
    _name = 'ev.device'
    _description = 'EV Telemetry Device'
    _order = 'name asc'
    _rec_name = 'device_id_code'

    device_id_code = fields.Char(
        string='Device ID',
        required=True,
        copy=False,
        help='Unique device serial number or identifier from .dat file',
    )
    name = fields.Char(
        string='Device Name',
        required=True,
    )
    vehicle_id = fields.Many2one(
        'fleet.vehicle',
        string='Linked Vehicle',
        ondelete='set null',
        help='The fleet vehicle this device is installed on',
    )
    device_type = fields.Selection(
        [
            ('bms', 'Battery Management System (BMS)'),
            ('telematics', 'Telematics Unit'),
            ('obd', 'OBD-II Adapter'),
            ('gateway', 'Fleet Gateway'),
        ],
        string='Device Type',
        default='telematics',
        required=True,
    )
    firmware_version = fields.Char(
        string='Firmware Version',
    )
    imei = fields.Char(
        string='IMEI / SIM',
        help='IMEI or SIM card number of the telematics device',
    )
    install_date = fields.Date(
        string='Installation Date',
    )
    last_sync = fields.Datetime(
        string='Last Sync',
        readonly=True,
    )
    status = fields.Selection(
        [
            ('active', 'Active'),
            ('inactive', 'Inactive'),
            ('error', 'Error / Fault'),
        ],
        string='Status',
        default='active',
        required=True,
    )
    battery_log_ids = fields.One2many(
        'ev.battery.log',
        'device_id',
        string='Battery Logs',
    )
    log_count = fields.Integer(
        string='Log Count',
        compute='_compute_log_count',
    )
    notes = fields.Text(
        string='Notes',
    )

    @api.depends('battery_log_ids')
    def _compute_log_count(self):
        for rec in self:
            rec.log_count = len(rec.battery_log_ids)

    def action_view_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Battery Logs – {self.device_id_code}',
            'res_model': 'ev.battery.log',
            'view_mode': 'list,form',
            'domain': [('device_id', '=', self.id)],
            'context': {'default_device_id': self.id},
        }
