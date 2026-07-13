# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from datetime import date


class EvTelemetryLog(models.Model):
    _name = 'ev.telemetry.log'
    _description = 'EV GPS / Telematics Telemetry Log'
    _order = 'timestamp desc, id desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    device_id = fields.Many2one(
        'ev.device',
        string='Telemetry Device',
        ondelete='cascade',
        required=True,
    )
    vehicle_id = fields.Many2one(
        'fleet.vehicle',
        string='EV Vehicle',
        related='device_id.vehicle_id',
        store=True,
        readonly=True,
    )
    import_batch_id = fields.Many2one(
        'ev.import.batch',
        string='Import Batch',
        ondelete='set null',
        readonly=True,
    )
    raw_import_source = fields.Char(
        string='Source File',
        readonly=True,
    )

    # ── Timestamp ─────────────────────────────────────────────────────────────
    timestamp = fields.Datetime(
        string='Timestamp',
        required=True,
        index=True,
    )
    log_date = fields.Date(
        string='Date',
        compute='_compute_log_date',
        store=True,
    )

    # ── GPS Position ──────────────────────────────────────────────────────────
    latitude = fields.Float(
        string='Latitude',
        digits=(10, 6),
    )
    longitude = fields.Float(
        string='Longitude',
        digits=(10, 6),
    )
    altitude = fields.Float(
        string='Altitude (m)',
        digits=(8, 2),
    )
    heading = fields.Float(
        string='Heading (°)',
        help='Compass heading in degrees (0–360)',
    )
    gps_status = fields.Selection(
        [
            ('A', 'Active / Valid Fix'),
            ('V', 'Void / No Fix'),
            ('D', 'Differential'),
            ('unknown', 'Unknown'),
        ],
        string='GPS Status',
        default='unknown',
    )
    satellites = fields.Integer(
        string='Satellites',
        help='Number of GPS satellites in view',
    )

    # ── Motion ────────────────────────────────────────────────────────────────
    speed = fields.Float(
        string='Speed (km/h)',
        digits=(8, 2),
    )
    odometer = fields.Float(
        string='Odometer (km)',
        digits=(12, 2),
    )
    ignition = fields.Boolean(
        string='Ignition ON',
        default=False,
    )

    # ── Power ─────────────────────────────────────────────────────────────────
    battery_voltage = fields.Float(
        string='Battery Voltage (V)',
        digits=(6, 2),
    )

    # ── Raw Payload ───────────────────────────────────────────────────────────
    raw_payload = fields.Text(
        string='Raw Payload',
        readonly=True,
        help='Original $NRM,... payload string from the .dat file',
    )

    @api.depends('timestamp')
    def _compute_log_date(self):
        for rec in self:
            rec.log_date = rec.timestamp.date() if rec.timestamp else date.today()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('ev.telemetry.log.sequence') or '/'
                )
        return super().create(vals_list)

    def action_view_on_map(self):
        """Open Google Maps at the GPS position."""
        self.ensure_one()
        if self.latitude and self.longitude:
            return {
                'type': 'ir.actions.act_url',
                'url': f'https://maps.google.com/?q={self.latitude},{self.longitude}',
                'target': 'new',
            }
