# -*- coding: utf-8 -*-

from odoo import models, fields, api, _


class EvImportBatch(models.Model):
    _name = 'ev.import.batch'
    _description = 'EV Data Import Batch'
    _order = 'import_date desc, id desc'

    name = fields.Char(
        string='Batch Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    import_date = fields.Datetime(
        string='Import Date',
        default=fields.Datetime.now,
        readonly=True,
    )
    imported_by = fields.Many2one(
        'res.users',
        string='Imported By',
        default=lambda self: self.env.user,
        readonly=True,
    )
    fleet_filename = fields.Char(
        string='Fleet File',
    )
    device_filename = fields.Char(
        string='Device/Telemetry File',
    )
    vehicles_created = fields.Integer(
        string='Vehicles Created',
        default=0,
        readonly=True,
    )
    vehicles_updated = fields.Integer(
        string='Vehicles Updated',
        default=0,
        readonly=True,
    )
    devices_created = fields.Integer(
        string='Devices Created',
        default=0,
        readonly=True,
    )
    logs_created = fields.Integer(
        string='Battery Logs Created',
        default=0,
        readonly=True,
    )
    status = fields.Selection(
        [
            ('pending', 'Pending'),
            ('success', 'Success'),
            ('partial', 'Partial Success'),
            ('failed', 'Failed'),
        ],
        string='Status',
        default='pending',
        readonly=True,
    )
    notes = fields.Text(
        string='Import Notes / Errors',
        readonly=True,
    )
    battery_log_ids = fields.One2many(
        'ev.battery.log',
        'import_batch_id',
        string='Imported Battery Logs',
    )
    telemetry_log_ids = fields.One2many(
        'ev.telemetry.log',
        'import_batch_id',
        string='Imported Telemetry Logs',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('ev.import.batch.sequence') or '/'
        return super().create(vals_list)
