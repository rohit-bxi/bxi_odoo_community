# -*- coding: utf-8 -*-
import logging
import re

from odoo import api, fields, models, _
from odoo.addons.base.models.res_partner import _tz_get
from odoo.exceptions import UserError, ValidationError

from .glpi_client import GLPI_ITEMTYPES, GlpiClient, GlpiError

_logger = logging.getLogger(__name__)

# config boolean field -> GLPI item type
ITEMTYPE_TOGGLES = {
    'sync_computer': 'Computer',
    'sync_printer': 'Printer',
    'sync_monitor': 'Monitor',
    'sync_peripheral': 'Peripheral',
    'sync_phone': 'Phone',
    'sync_network_equipment': 'NetworkEquipment',
}


class GlpiConfig(models.Model):
    _name = 'glpi.config'
    _description = 'GLPI Connection'

    name = fields.Char(string='Name', required=True, default='GLPI')
    active = fields.Boolean(default=True)

    # ─── Connection ──────────────────────────────────────────────────────────
    base_url = fields.Char(string='GLPI URL', required=True,
        help="Root URL of GLPI, e.g. https://glpi.example.com (without /api.php).")
    api_version = fields.Char(string='API Version', required=True, default='v2',
        help="High-Level API version segment. 'v2' always follows the latest v2.x.")
    client_id = fields.Char(string='OAuth Client ID', groups='base.group_system',
        help="From GLPI Setup > OAuth Clients. The client must allow the Password grant.")
    client_secret = fields.Char(string='OAuth Client Secret', groups='base.group_system')
    username = fields.Char(string='GLPI Username', groups='base.group_system')
    password = fields.Char(string='GLPI Password', groups='base.group_system')
    scope = fields.Char(string='Scope', required=True, default='api')
    entity_id = fields.Integer(string='GLPI Entity ID',
        help="Entity to work in. Leave 0 to use the GLPI user's default entity.")
    entity_recursive = fields.Boolean(string='Include Sub-entities', default=True)
    verify_ssl = fields.Boolean(string='Verify SSL Certificate', default=True)
    timeout = fields.Integer(string='Timeout (s)', default=30)
    page_size = fields.Integer(string='Page Size', default=100)
    glpi_tz = fields.Selection(_tz_get, string='GLPI Timezone',
        default=lambda self: self.env.user.tz or 'UTC',
        help="Timezone of dates returned by GLPI when they carry no offset.")
    insecure_url = fields.Boolean(compute='_compute_insecure_url')

    # ─── Item Types ──────────────────────────────────────────────────────────
    sync_computer = fields.Boolean(string='Computers', default=True)
    sync_printer = fields.Boolean(string='Printers', default=True)
    sync_monitor = fields.Boolean(string='Monitors', default=False,
        help="GLPI Agent also reports built-in laptop screens as monitors.")
    sync_peripheral = fields.Boolean(string='Peripherals', default=False,
        help="GLPI Agent reports USB drives, adapters and phones as peripherals.")
    sync_phone = fields.Boolean(string='Phones', default=False)
    sync_network_equipment = fields.Boolean(string='Network Equipment', default=False)

    # ─── Import Rules (GLPI -> Odoo) ─────────────────────────────────────────
    auto_create_assets = fields.Boolean(string='Create Draft Assets', default=True,
        help="Create a Draft asset for GLPI items that match no existing asset.")
    skip_without_serial = fields.Boolean(string='Skip Items Without Serial', default=True)
    skip_name_pattern = fields.Char(string='Skip Names Matching',
        default=r"^poc_|['\";]",
        help="Python regular expression. GLPI items whose name matches are ignored.")
    import_custodian_on_create = fields.Boolean(string='Import Custodian on Create', default=True,
        help="When a new asset is created from GLPI, assign it to the employee matching "
             "the GLPI user. Afterwards Odoo stays the custodian master.")
    create_products = fields.Boolean(string='Create Missing Products', default=False,
        help="Create a product named '<Manufacturer> <Model>' when none exists.")
    default_asset_type_id = fields.Many2one('asset.type', string='Default Asset Type',
        help="Used when no Type Mapping matches the GLPI item.")
    responsible_user_id = fields.Many2one('res.users', string='Review Responsible',
        default=lambda self: self.env.user,
        help="Receives activities for custodian mismatches and items removed from GLPI.")

    # ─── Write-back (Odoo -> GLPI) ───────────────────────────────────────────
    write_back_enabled = fields.Boolean(string='Enable Write-back to GLPI', default=False,
        help="Requires a GLPI profile with write rights on assets.")
    push_inventory_number = fields.Boolean(string='Asset Reference -> Inventory Number', default=True)
    push_custodian = fields.Boolean(string='Custodian -> GLPI User', default=True)
    push_status = fields.Boolean(string='Operational Status -> GLPI Status', default=True)
    push_location = fields.Boolean(string='Location -> GLPI Location', default=True)
    push_financials = fields.Boolean(string='Financial Info -> GLPI Infocom', default=True)
    export_new_assets = fields.Boolean(string='Create Odoo-only Assets in GLPI', default=False,
        help="During scheduled sync, create in GLPI the assets that have a serial number "
             "but no GLPI link.")
    export_itemtype = fields.Selection(GLPI_ITEMTYPES, string='Default GLPI Item Type',
        default='Computer',
        help="Item type used when exporting an asset whose type has no Type Mapping.")

    # ─── Status ──────────────────────────────────────────────────────────────
    log_ids = fields.One2many('glpi.sync.log', 'config_id', string='Sync Logs')
    log_count = fields.Integer(compute='_compute_log_count')
    last_sync_date = fields.Datetime(string='Last Sync', readonly=True)
    last_sync_state = fields.Selection([
        ('done', 'Success'),
        ('partial', 'Completed with Errors'),
        ('failed', 'Failed'),
    ], string='Last Sync Result', readonly=True)

    @api.depends('base_url')
    def _compute_insecure_url(self):
        for rec in self:
            rec.insecure_url = bool(rec.base_url) and not rec.base_url.strip().lower().startswith('https://')

    @api.depends('log_ids')
    def _compute_log_count(self):
        counts = dict(self.env['glpi.sync.log']._read_group(
            [('config_id', 'in', self.ids)], ['config_id'], ['__count']))
        for rec in self:
            rec.log_count = counts.get(rec, 0)

    @api.constrains('skip_name_pattern')
    def _check_skip_name_pattern(self):
        for rec in self.filtered('skip_name_pattern'):
            try:
                re.compile(rec.skip_name_pattern)
            except re.error as e:
                raise ValidationError(_("Invalid 'Skip Names Matching' expression: %s", e))

    @api.constrains('page_size', 'timeout')
    def _check_limits(self):
        for rec in self:
            if rec.page_size < 1 or rec.timeout < 1:
                raise ValidationError(_("Page size and timeout must be positive."))

    # =========================================================================
    # HELPERS
    # =========================================================================

    @api.model
    def _get_active(self):
        return self.sudo().search([('active', '=', True)], order='id', limit=1)

    def _glpi_client(self):
        self.ensure_one()
        return GlpiClient(self.sudo())

    def _enabled_itemtypes(self):
        self.ensure_one()
        return [itemtype for field, itemtype in ITEMTYPE_TOGGLES.items() if self[field]]

    # =========================================================================
    # ACTIONS
    # =========================================================================

    def action_test_connection(self):
        self.ensure_one()
        try:
            client = self._glpi_client()
            counts = [f"{itemtype}: {client.count_assets(itemtype)}"
                      for itemtype in self._enabled_itemtypes() or ['Computer']]
        except GlpiError as e:
            raise UserError(_("Connection to GLPI failed.\n\n%s", e)) from e
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('GLPI connection successful'),
                'message': ', '.join(counts),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_open_sync_wizard(self):
        self.ensure_one()
        return {
            'name': _('Run GLPI Sync'),
            'type': 'ir.actions.act_window',
            'res_model': 'glpi.sync.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_config_id': self.id},
        }

    def action_view_logs(self):
        self.ensure_one()
        return {
            'name': _('GLPI Sync Logs'),
            'type': 'ir.actions.act_window',
            'res_model': 'glpi.sync.log',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.id)],
        }

    def _run_sync(self, pull=True, push=True, dry_run=False, trigger='manual', assets=None):
        """Run one synchronisation and return its ``glpi.sync.log``."""
        self.ensure_one()
        return self.env['glpi.sync']._run(
            self, pull=pull, push=push, dry_run=dry_run, trigger=trigger, assets=assets)

    @api.model
    def _cron_sync(self):
        config = self._get_active()
        if not config:
            _logger.info("GLPI sync skipped: no active GLPI connection configured.")
            return
        config.with_context(glpi_cron=True)._run_sync(trigger='cron')
