# -*- coding: utf-8 -*-
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .glpi_client import GLPI_ITEMTYPES, GlpiError

# Odoo-owned fields: changing any of them queues a push to GLPI.
GLPI_PUSH_TRIGGER_FIELDS = {
    'name', 'employee_id', 'status', 'location_description', 'state',
    'amount', 'invoice_date', 'capitalized_date', 'invoice_id',
    'warranty_date', 'warranty_expiry_date', 'vendor_id', 'disposal_date',
}
TRANSFER_TRIGGER_FIELDS = {'asset_id', 'transfer_employee_id', 'status'}


class Asset(models.Model):
    _inherit = 'asset.management'

    glpi_id = fields.Integer(string='GLPI ID', copy=False, readonly=True, index=True)
    glpi_itemtype = fields.Selection(GLPI_ITEMTYPES, string='GLPI Item Type',
                                     copy=False, readonly=True)
    glpi_sync_state = fields.Selection([
        ('linked', 'Linked'),
        ('trashed', 'In GLPI Trash'),
        ('missing', 'Missing in GLPI'),
    ], string='GLPI Sync State', copy=False, readonly=True, tracking=True)
    glpi_url = fields.Char(string='GLPI Link', compute='_compute_glpi_url')

    # Facts reported by GLPI (GLPI is the master for these)
    glpi_name = fields.Char(string='GLPI Name / Hostname', copy=False, readonly=True)
    glpi_uuid = fields.Char(string='GLPI UUID', copy=False, readonly=True)
    glpi_inventory_number = fields.Char(string='GLPI Inventory Number', copy=False, readonly=True)
    glpi_manufacturer = fields.Char(string='Manufacturer', copy=False, readonly=True)
    glpi_model = fields.Char(string='Model', copy=False, readonly=True)
    glpi_type = fields.Char(string='GLPI Type', copy=False, readonly=True)
    glpi_status = fields.Char(string='GLPI Status', copy=False, readonly=True)
    glpi_location = fields.Char(string='GLPI Location', copy=False, readonly=True)
    glpi_contact = fields.Char(string='Logged-in User (Agent)', copy=False, readonly=True)
    glpi_user_id = fields.Integer(string='GLPI User ID', copy=False, readonly=True)
    glpi_user_name = fields.Char(string='GLPI User', copy=False, readonly=True)
    glpi_specs = fields.Text(string='Hardware Specs (GLPI)', copy=False, readonly=True)
    glpi_infocom_id = fields.Integer(string='GLPI Infocom ID', copy=False, readonly=True)
    glpi_last_inventory = fields.Datetime(string='Last Agent Inventory', copy=False, readonly=True)
    glpi_date_mod = fields.Datetime(string='Modified in GLPI', copy=False, readonly=True)
    glpi_last_pull = fields.Datetime(string='Last Pulled', copy=False, readonly=True)
    glpi_last_push = fields.Datetime(string='Last Pushed', copy=False, readonly=True)

    # Sync flags
    glpi_push_pending = fields.Boolean(string='GLPI Push Pending', copy=False, readonly=True,
        help="Odoo-owned values changed since the last push to GLPI.")
    glpi_custodian_mismatch = fields.Boolean(string='GLPI Custodian Mismatch', copy=False,
        readonly=True, tracking=True,
        help="GLPI reports a different user than the Odoo custodian. Odoo is the master: "
             "push to GLPI to overwrite, or update the custodian in Odoo.")

    _glpi_item_uniq = models.UniqueIndex(
        '(glpi_itemtype, glpi_id) WHERE glpi_id > 0',
        "This GLPI item is already linked to another asset.",
    )

    @api.depends('glpi_id', 'glpi_itemtype')
    def _compute_glpi_url(self):
        base_url = (self.env['glpi.config']._get_active().base_url or '').rstrip('/')
        for rec in self:
            rec.glpi_url = (
                f"{base_url}/front/{rec.glpi_itemtype.lower()}.form.php?id={rec.glpi_id}"
                if base_url and rec.glpi_id and rec.glpi_itemtype else False)

    def write(self, vals):
        if not self.env.context.get('glpi_sync') and GLPI_PUSH_TRIGGER_FIELDS.intersection(vals):
            vals = dict(vals, glpi_push_pending=True)
        return super().write(vals)

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _glpi_custodian(self):
        """Employee currently holding the asset: the latest assigned transfer,
        falling back to the Current Custodian field."""
        self.ensure_one()
        assigned = self.sudo().transfer_ids.filtered(lambda t: t.status == 'assigned').sorted(
            lambda t: (t.assign_date or date.min, t.id))
        return assigned[-1:].transfer_employee_id or self.employee_id

    def _glpi_config_or_raise(self, need_write_back=False):
        config = self.env['glpi.config']._get_active()
        if not config:
            raise UserError(_("No active GLPI connection is configured."))
        if need_write_back and not config.write_back_enabled:
            raise UserError(_("Write-back to GLPI is disabled in the GLPI connection settings."))
        return config

    def _glpi_open_log(self, log):
        if log.state in ('done', 'partial') and not log.error_count:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('GLPI sync finished'),
                    'message': ', '.join(
                        f"{line.asset_id.name or line.glpi_name}: {line.message or line.action}"
                        for line in log.line_ids[:5]) or _('Nothing to do.'),
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                },
            }
        return {
            'name': _('GLPI Sync Log'),
            'type': 'ir.actions.act_window',
            'res_model': 'glpi.sync.log',
            'res_id': log.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # =========================================================================
    # ACTIONS
    # =========================================================================

    def action_open_in_glpi(self):
        self.ensure_one()
        if not self.glpi_url:
            raise UserError(_("This asset is not linked to GLPI."))
        return {'type': 'ir.actions.act_url', 'url': self.glpi_url, 'target': 'new'}

    def action_glpi_sync(self):
        """Pull this asset from GLPI, then push Odoo-owned values if write-back is on."""
        config = self._glpi_config_or_raise()
        linked = self.filtered('glpi_id')
        if not linked:
            raise UserError(_("Select assets that are linked to GLPI."))
        log = config._run_sync(trigger='asset', assets=linked)
        return self._glpi_open_log(log)

    def action_glpi_push(self):
        config = self._glpi_config_or_raise(need_write_back=True)
        linked = self.filtered('glpi_id')
        if not linked:
            raise UserError(_("Select assets that are linked to GLPI."))
        linked.with_context(glpi_sync=True).write({'glpi_push_pending': True})
        log = config._run_sync(pull=False, trigger='asset', assets=linked)
        return self._glpi_open_log(log)

    def action_glpi_export(self):
        """Create the selected Odoo-only assets in GLPI."""
        config = self._glpi_config_or_raise(need_write_back=True)
        to_export = self.filtered(lambda a: not a.glpi_id)
        if not to_export:
            raise UserError(_("The selected assets are already linked to GLPI."))
        try:
            log = self.env['glpi.sync']._run(
                config, pull=False, push=True, trigger='asset', assets=to_export, export=True)
        except GlpiError as e:
            raise UserError(str(e)) from e
        return self._glpi_open_log(log)

    def action_glpi_unlink(self):
        self.with_context(glpi_sync=True).write({
            'glpi_id': False,
            'glpi_itemtype': False,
            'glpi_sync_state': False,
            'glpi_infocom_id': False,
            'glpi_push_pending': False,
            'glpi_custodian_mismatch': False,
        })
        for rec in self:
            rec.message_post(body=_("Unlinked from GLPI."))
        return True


class AssetTransferEntry(models.Model):
    _inherit = 'asset.transfer.entry'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get('glpi_sync'):
            records._glpi_mark_push_pending()
        return records

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('glpi_sync') and TRANSFER_TRIGGER_FIELDS.intersection(vals):
            self._glpi_mark_push_pending()
        return res

    def _glpi_mark_push_pending(self):
        # Transfer users may not have write access to the asset itself.
        assets = self.sudo().asset_id.filtered('glpi_id')
        if assets:
            assets.with_context(glpi_sync=True).write({'glpi_push_pending': True})
