# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

LOG_RETENTION_DAYS = 90

LINE_ACTIONS = [
    ('created', 'Created'),
    ('linked', 'Linked'),
    ('updated', 'Updated'),
    ('skipped', 'Skipped'),
    ('conflict', 'Conflict'),
    ('mismatch', 'Custodian Mismatch'),
    ('trashed', 'Trashed in GLPI'),
    ('missing', 'Missing in GLPI'),
    ('pushed', 'Pushed to GLPI'),
    ('exported', 'Created in GLPI'),
    ('error', 'Error'),
]

# log counter field per line action
COUNTERS = {
    'created': 'created_count',
    'linked': 'linked_count',
    'updated': 'updated_count',
    'skipped': 'skipped_count',
    'conflict': 'conflict_count',
    'mismatch': 'conflict_count',
    'trashed': 'missing_count',
    'missing': 'missing_count',
    'pushed': 'pushed_count',
    'exported': 'exported_count',
    'error': 'error_count',
}


class GlpiSyncLog(models.Model):
    _name = 'glpi.sync.log'
    _description = 'GLPI Sync Log'
    _order = 'id desc'

    name = fields.Char(string='Run', compute='_compute_name', store=True)
    config_id = fields.Many2one('glpi.config', string='GLPI Connection', required=True,
                                ondelete='cascade')
    trigger = fields.Selection([
        ('manual', 'Manual'),
        ('cron', 'Scheduled'),
        ('asset', 'Single Asset'),
    ], string='Trigger', required=True, default='manual')
    dry_run = fields.Boolean(string='Dry Run', readonly=True)
    start_date = fields.Datetime(string='Started', default=fields.Datetime.now, readonly=True)
    end_date = fields.Datetime(string='Finished', readonly=True)
    state = fields.Selection([
        ('running', 'Running'),
        ('done', 'Success'),
        ('partial', 'Completed with Errors'),
        ('failed', 'Failed'),
    ], string='Result', default='running', readonly=True)
    message = fields.Text(string='Message', readonly=True)

    fetched_count = fields.Integer(string='Fetched', readonly=True)
    unchanged_count = fields.Integer(string='Unchanged', readonly=True)
    created_count = fields.Integer(string='Created', readonly=True)
    linked_count = fields.Integer(string='Linked', readonly=True)
    updated_count = fields.Integer(string='Updated', readonly=True)
    skipped_count = fields.Integer(string='Skipped', readonly=True)
    conflict_count = fields.Integer(string='Conflicts', readonly=True)
    missing_count = fields.Integer(string='Removed in GLPI', readonly=True)
    pushed_count = fields.Integer(string='Pushed', readonly=True)
    exported_count = fields.Integer(string='Created in GLPI', readonly=True)
    error_count = fields.Integer(string='Errors', readonly=True)

    line_ids = fields.One2many('glpi.sync.log.line', 'log_id', string='Details')

    @api.depends('start_date', 'dry_run')
    def _compute_name(self):
        for rec in self:
            start = fields.Datetime.context_timestamp(rec, rec.start_date or fields.Datetime.now())
            rec.name = '%s%s' % (start.strftime('%Y-%m-%d %H:%M'), ' (dry run)' if rec.dry_run else '')

    @api.autovacuum
    def _gc_old_logs(self):
        limit = fields.Datetime.now() - relativedelta(days=LOG_RETENTION_DAYS)
        self.search([('start_date', '<', limit), ('state', '!=', 'running')]).unlink()


class GlpiSyncLogLine(models.Model):
    _name = 'glpi.sync.log.line'
    _description = 'GLPI Sync Log Line'
    _order = 'id'

    log_id = fields.Many2one('glpi.sync.log', required=True, ondelete='cascade', index=True)
    level = fields.Selection([
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ], string='Level', default='info', required=True)
    action = fields.Selection(LINE_ACTIONS, string='Action', required=True)
    glpi_itemtype = fields.Char(string='GLPI Item Type')
    glpi_id = fields.Integer(string='GLPI ID')
    glpi_name = fields.Char(string='GLPI Name')
    asset_id = fields.Many2one('asset.management', string='Asset', ondelete='set null')
    message = fields.Text(string='Message')
