# -*- coding: utf-8 -*-
"""
GLPI <-> Odoo synchronisation engine.

Field ownership (each field has exactly one master, so the two directions
never fight):

* GLPI -> Odoo on every pull: serial number, hostname, manufacturer / model /
  type, hardware specs, logged-in user, GLPI user, last inventory, trash state.
* GLPI -> Odoo once, when an asset is created or first linked, and only into
  empty fields: asset type, product, location, inventory number, specs,
  custodian (create only) and financial data (Draft assets only).
* Odoo -> GLPI on push: asset reference (inventory number), custodian (GLPI
  user), operational status, location and Infocom (value, dates, warranty,
  supplier).
"""
import logging
import re
from collections import defaultdict
from datetime import datetime

import pytz
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, Command, _
from odoo.tools import float_compare
from odoo.tools.sql import escape_psql

from .glpi_client import COMPONENT_KINDS, ITEMTYPE_PATHS, GlpiError
from .glpi_mapping import _normalize_login
from .glpi_sync_log import COUNTERS

_logger = logging.getLogger(__name__)

COMMIT_BATCH = 25
# Fields refreshed on every pull that do not count as a real change.
BOOKKEEPING_FIELDS = {'glpi_date_mod', 'glpi_last_pull', 'glpi_last_inventory'}
WARNING_ACTIONS = {'conflict', 'mismatch', 'trashed', 'missing'}
# Asset Type defaults copied onto an asset when the type is set from a Type Mapping.
TYPE_ACCOUNT_FIELDS = ('fixed_asset_account_id', 'depreciation_expense_account_id',
                       'accumulated_depreciation_account_id', 'asset_journal_id',
                       'asset_clearing_account_id')


class GlpiSync(models.AbstractModel):
    _name = 'glpi.sync'
    _description = 'GLPI Synchronisation Engine'

    @api.model
    def _run(self, config, pull=True, push=True, dry_run=False, trigger='manual',
             assets=None, export=None):
        """
        :param assets: restrict the run to these assets (pull/push by id
            instead of listing GLPI, no missing-item detection)
        :param export: create Odoo-only assets in GLPI; None follows the
            connection setting
        """
        log = self.env['glpi.sync.log'].sudo().create({
            'config_id': config.id,
            'trigger': trigger,
            'dry_run': dry_run,
        })
        run = _SyncRun(self.env, config, log, dry_run, assets)
        message = False
        try:
            run.client = config._glpi_client()
            if pull:
                run.pull()
            if push and not dry_run:
                run.push(export=export)
            state = 'partial' if run.counts['error_count'] else 'done'
        except GlpiError as e:
            _logger.warning("GLPI sync failed: %s", e)
            state, message = 'failed', str(e)
        log.write(dict(run.counts, state=state, message=message, end_date=fields.Datetime.now()))
        if not dry_run:
            config.sudo().write({'last_sync_date': log.end_date, 'last_sync_state': state})
        return log


def _ref_name(value):
    """Name of an embedded GLPI relation ({'id': 3, 'name': 'Dell Inc.'})."""
    if isinstance(value, dict) and value.get('id'):
        return (value.get('name') or '').strip() or False
    return False


def _format_size(megabytes):
    if megabytes >= 1024:
        return f"{round(megabytes / 1024)} GB"
    return f"{megabytes} MB"


def _to_date(value):
    try:
        return fields.Date.to_date(str(value)[:10]) if value else False
    except ValueError:
        return False


class _SyncRun:
    """State of one synchronisation run (client, caches, counters, log)."""

    def __init__(self, env, config, log, dry_run, assets):
        self.env = env
        self.config = config.sudo()
        self.log = log
        self.dry_run = dry_run
        self.assets = assets.sudo() if assets is not None else None
        self.client = None
        self.counts = defaultdict(int)
        self.Asset = env['asset.management'].sudo().with_context(glpi_sync=True)
        self.tz = pytz.timezone(self.config.glpi_tz or 'UTC')
        self.skip_re = re.compile(self.config.skip_name_pattern) if self.config.skip_name_pattern else None
        self._cache = {}
        self._warned = set()
        self._processed = 0

    # =========================================================================
    # LOGGING / BOOKKEEPING
    # =========================================================================

    def count(self, action):
        self.counts[COUNTERS[action]] += 1

    def line(self, action, item=None, itemtype=None, asset=None, message=None, level=None):
        self.count(action)
        if level is None:
            level = 'error' if action == 'error' else 'warning' if action in WARNING_ACTIONS else 'info'
        self.env['glpi.sync.log.line'].sudo().create({
            'log_id': self.log.id,
            'level': level,
            'action': action,
            'glpi_itemtype': itemtype or (asset and asset.glpi_itemtype) or False,
            'glpi_id': (item or {}).get('id') or (asset and asset.glpi_id) or 0,
            'glpi_name': (item or {}).get('name') or (asset and asset.glpi_name) or False,
            'asset_id': asset.id if asset else False,
            'message': message or False,
        })

    def warn_once(self, key, message):
        if key not in self._warned:
            self._warned.add(key)
            self.line('error', message=message, level='warning')

    def checkpoint(self):
        """Commit every few items when running from the scheduler, so a
        crash late in the run does not lose the work already done."""
        self._processed += 1
        if (self.env.context.get('glpi_cron') and not self.dry_run
                and self._processed % COMMIT_BATCH == 0):
            self.env['ir.cron']._commit_progress(processed=COMMIT_BATCH)

    def guarded(self, func, *args, item=None, itemtype=None, asset=None):
        """Run ``func`` in a savepoint; one bad record must not stop the run."""
        try:
            with self.env.cr.savepoint():
                func(*args)
        except GlpiError as e:
            _logger.warning("GLPI sync error on %s %s: %s", itemtype, (item or {}).get('id') or asset, e)
            self.line('error', item=item, itemtype=itemtype, asset=asset, message=str(e))
        except Exception as e:  # noqa: BLE001
            _logger.exception("GLPI sync error on %s %s", itemtype, (item or {}).get('id') or asset)
            self.line('error', item=item, itemtype=itemtype, asset=asset, message=str(e))
        self.checkpoint()

    def parse_dt(self, value):
        if not value:
            return False
        try:
            dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            return False
        if dt.tzinfo is None:
            dt = self.tz.localize(dt)
        return dt.astimezone(pytz.utc).replace(tzinfo=None, microsecond=0)

    # =========================================================================
    # GLPI LOOKUPS (loaded once per run)
    # =========================================================================

    def _load(self, key, loader, label):
        if key not in self._cache:
            try:
                self._cache[key] = loader()
            except GlpiError as e:
                self._cache[key] = []
                self.warn_once(key, _("Could not read GLPI %(label)s: %(error)s", label=label, error=e))
        return self._cache[key]

    def glpi_users(self):
        """(by id, by normalised login, by lower-case email)"""
        if 'user_index' not in self._cache:
            by_id, by_login, by_email = {}, {}, {}
            for user in self._load('users', self.client.list_users, _('users')):
                by_id[user.get('id')] = user
                if user.get('username'):
                    by_login[_normalize_login(user['username'])] = user
                for email in user.get('emails') or []:
                    if email.get('email'):
                        by_email.setdefault(email['email'].strip().lower(), user)
            self._cache['user_index'] = (by_id, by_login, by_email)
        return self._cache['user_index']

    def named_ids(self, key, loader, label):
        """{lower-case name or complete name: id} for a GLPI dropdown."""
        index_key = f'{key}_index'
        if index_key not in self._cache:
            index = {}
            for row in self._load(key, loader, label):
                for name in (row.get('completename'), row.get('name')):
                    if name:
                        index.setdefault(name.strip().lower(), row['id'])
            self._cache[index_key] = index
        return self._cache[index_key]

    # =========================================================================
    # PULL  (GLPI -> Odoo)
    # =========================================================================

    def pull(self):
        if self.assets is not None:
            for asset in self.assets.filtered(lambda a: a.glpi_id and a.glpi_itemtype):
                self.guarded(self.pull_one, asset, asset=asset)
            return
        for itemtype in self.config._enabled_itemtypes():
            try:
                items = self.client.list_assets(itemtype)
            except GlpiError as e:
                if e.status_code != 403:
                    raise
                # No right on this item type: report it, keep syncing the others.
                self.line('error', itemtype=itemtype, message=str(e))
                continue
            self.counts['fetched_count'] += len(items)
            linked = {a.glpi_id: a for a in self.Asset.search([
                ('glpi_itemtype', '=', itemtype), ('glpi_id', '>', 0)])}
            for item in items:
                self.guarded(self.pull_item, itemtype, item, linked, item=item, itemtype=itemtype)
            seen = {item.get('id') for item in items}
            for asset in linked.values():
                if asset.glpi_id not in seen and asset.glpi_sync_state != 'missing':
                    self.guarded(self.mark_missing, asset, asset=asset)

    def pull_one(self, asset):
        asset = asset.with_context(glpi_sync=True)
        item = self.client.request(
            'GET', f'{ITEMTYPE_PATHS[asset.glpi_itemtype]}/{asset.glpi_id}', allow_404=True)
        self.counts['fetched_count'] += 1
        if not item:
            self.mark_missing(asset)
            return
        self.pull_item(asset.glpi_itemtype, item, {asset.glpi_id: asset}, force=True)

    def skip_reason(self, item):
        name = item.get('name') or ''
        if item.get('is_template'):
            return _('template')
        if self.skip_re and self.skip_re.search(name):
            return _('name matches the skip pattern')
        if self.config.skip_without_serial and not (item.get('serial') or '').strip():
            return _('no serial number')
        return False

    def pull_item(self, itemtype, item, linked, force=False):
        glpi_id = item.get('id')
        asset = linked.get(glpi_id)
        action = 'updated'
        if not asset:
            reason = self.skip_reason(item)
            if reason:
                if self.dry_run:
                    self.line('skipped', item, itemtype, message=reason)
                else:
                    self.count('skipped')
                return
            matches = self.match_existing(item)
            if len(matches) > 1:
                self.line('conflict', item, itemtype, message=_(
                    "Matches several assets (%s); link it manually.", ', '.join(matches.mapped('name'))))
                return
            if matches:
                asset, action = matches, 'linked'
            elif not self.config.auto_create_assets:
                if self.dry_run:
                    self.line('skipped', item, itemtype, message=_('no matching asset'))
                else:
                    self.count('skipped')
                return
            else:
                action = 'created'

        date_mod = self.parse_dt(item.get('date_mod'))
        if (action == 'updated' and not force and date_mod
                and asset.glpi_sync_state == 'linked' and asset.glpi_date_mod == date_mod):
            self.counts['unchanged_count'] += 1
            return

        details = self.fetch_details(itemtype, item)
        vals = self.glpi_vals(itemtype, item, details)
        if action == 'created':
            self.create_asset(itemtype, item, details, vals, linked)
            return

        if action == 'linked':
            vals.update(self.initial_vals(itemtype, item, details, asset))
            vals.update(glpi_id=glpi_id, glpi_itemtype=itemtype, glpi_push_pending=True)
        changes = self.diff(asset, vals)
        meaningful = sorted(set(changes) - BOOKKEEPING_FIELDS)
        if self.dry_run:
            if action == 'linked' or meaningful:
                self.line(action, item, itemtype, asset, message=', '.join(meaningful))
            else:
                self.counts['unchanged_count'] += 1
            return

        previous_state = asset.glpi_sync_state
        previous_serial = asset.serial_number
        asset.write(changes)
        linked[glpi_id] = asset
        if 'serial_number' in changes and previous_serial:
            asset.message_post(body=_("Serial number changed in GLPI: %(old)s → %(new)s",
                                      old=previous_serial, new=asset.serial_number))
        self.track_glpi_state(asset, previous_state)
        self.check_custodian(asset, item)
        if action == 'linked' or meaningful:
            self.line(action, item, itemtype, asset, message=', '.join(meaningful))
        else:
            self.counts['unchanged_count'] += 1

    def create_asset(self, itemtype, item, details, vals, linked):
        vals.update(self.initial_vals(itemtype, item, details, None))
        vals.update(glpi_id=item['id'], glpi_itemtype=itemtype, glpi_push_pending=True)
        custodian = self.env['hr.employee']
        if self.config.import_custodian_on_create:
            custodian = self.employee_for_item(item, use_contact=True)
            if custodian:
                vals['employee_id'] = custodian.id
                vals.setdefault('status', 'assign')
        if self.dry_run:
            message = _("New Draft asset '%s'", vals['asset_name'])
            if custodian:
                message += _(", assigned to %s", custodian.name)
            self.line('created', item, itemtype, message=message)
            return
        asset = self.Asset.create(vals)
        linked[item['id']] = asset
        if custodian:
            self.env['asset.transfer.entry'].sudo().with_context(glpi_sync=True).create({
                'asset_id': asset.id,
                'transfer_employee_id': custodian.id,
                'status': 'assigned',
                'notes': _('Imported from GLPI'),
            })
        asset.message_post(body=_("Created from GLPI %(itemtype)s #%(id)s.",
                                  itemtype=itemtype, id=item['id']))
        self.line('created', item, itemtype, asset)

    def match_existing(self, item):
        """Unlinked assets matching by serial, then inventory number, then hostname."""
        unlinked = ['|', ('glpi_id', '=', False), ('glpi_id', '=', 0)]
        serial = (item.get('serial') or '').strip()
        if serial:
            found = self.Asset.search(unlinked + [('serial_number', '=ilike', escape_psql(serial))])
            if found:
                return found
        otherserial = (item.get('otherserial') or '').strip()
        if otherserial:
            found = self.Asset.search(unlinked + [
                '|', ('barcode', '=ilike', escape_psql(otherserial)), ('name', '=', otherserial)])
            if found:
                return found
        name = (item.get('name') or '').strip()
        if name:
            return self.Asset.search(unlinked + [('asset_name', '=ilike', escape_psql(name))])
        return self.Asset

    def fetch_details(self, itemtype, item):
        details = {'infocom': None, 'infocom_ok': False, 'components': None}
        try:
            details['infocom'] = self.client.get_infocom(itemtype, item['id'])
            details['infocom_ok'] = True
        except GlpiError as e:
            if e.status_code != 403:
                raise
            self.warn_once('infocom', _("No GLPI right to read financial information: %s", e))
        if itemtype == 'Computer':
            try:
                details['components'] = {
                    kind: self.client.get_components(item['id'], kind) for kind in COMPONENT_KINDS}
            except GlpiError as e:
                if e.status_code != 403:
                    raise
                self.warn_once('components', _("No GLPI right to read components: %s", e))
        return details

    def glpi_vals(self, itemtype, item, details):
        """GLPI-owned fields, written on every pull."""
        user = item.get('user') or {}
        vals = {
            'glpi_name': item.get('name') or False,
            'glpi_uuid': item.get('uuid') or False,
            'glpi_inventory_number': item.get('otherserial') or False,
            'glpi_manufacturer': _ref_name(item.get('manufacturer')),
            'glpi_model': _ref_name(item.get('model')),
            'glpi_type': _ref_name(item.get('type')),
            'glpi_status': _ref_name(item.get('status')),
            'glpi_location': _ref_name(item.get('location')),
            'glpi_contact': item.get('contact') or False,
            'glpi_user_id': user.get('id') or 0,
            'glpi_user_name': _ref_name(user),
            'glpi_last_inventory': self.parse_dt(item.get('last_inventory_update')),
            'glpi_date_mod': self.parse_dt(item.get('date_mod')),
            'glpi_last_pull': fields.Datetime.now(),
            'glpi_sync_state': 'trashed' if item.get('is_deleted') else 'linked',
        }
        if details['components'] is not None:
            vals['glpi_specs'] = self.specs_text(details['components'])
        if details['infocom_ok']:
            vals['glpi_infocom_id'] = (details['infocom'] or {}).get('id') or 0
        serial = (item.get('serial') or '').strip()
        if serial:
            vals['serial_number'] = serial
        return vals

    def initial_vals(self, itemtype, item, details, asset):
        """Values taken from GLPI once, on create (asset is None) or first link,
        and only into empty fields."""
        def empty(fname):
            return asset is None or not asset[fname]

        vals = {}
        if asset is None:
            vals['asset_name'] = (item.get('name') or item.get('serial')
                                  or f"GLPI {itemtype} {item['id']}")
            vals['model_type'] = 'single'
        type_map = self.env['glpi.type.map'].sudo()._find(itemtype, _ref_name(item.get('type')))
        asset_type = type_map.asset_type_id or self.config.default_asset_type_id
        if asset_type and empty('asset_type_id'):
            vals['asset_type_id'] = asset_type.id
            # Same defaults as picking the type in the form (_onchange_asset_type).
            for fname in TYPE_ACCOUNT_FIELDS:
                if asset_type[fname] and empty(fname):
                    vals[fname] = asset_type[fname].id
        if asset is None and type_map.tag_ids:
            vals['tag_ids'] = [Command.set(type_map.tag_ids.ids)]
        if asset is None:
            status = self.env['glpi.status.map'].sudo()._odoo_status_for(_ref_name(item.get('status')))
            if status:
                vals['status'] = status
        location = _ref_name(item.get('location'))
        if location and empty('location_description'):
            vals['location_description'] = location
        otherserial = (item.get('otherserial') or '').strip()
        if otherserial and empty('barcode') and (asset is None or otherserial != asset.name):
            vals['barcode'] = otherserial
        product = self.product_for(item)
        if product and empty('product_id'):
            vals['product_id'] = product.id
        specs = details['components'] is not None and self.specs_text(details['components'])
        if specs and empty('asset_configuration'):
            vals['asset_configuration'] = specs
        if asset is None or asset.state == 'draft':
            vals.update(self.financial_vals(details['infocom'], asset))
        return vals

    def financial_vals(self, infocom, asset):
        """GLPI Infocom -> empty financial fields of a Draft asset."""
        if not infocom:
            return {}

        def empty(fname):
            return asset is None or not asset[fname]

        vals = {}
        if (infocom.get('value') or 0.0) > 0 and empty('amount'):
            vals['amount'] = infocom['value']
        for glpi_key, fname in (('date_buy', 'invoice_date'),
                                ('date_use', 'capitalized_date'),
                                ('date_warranty', 'warranty_date')):
            value = _to_date(infocom.get(glpi_key))
            if value and empty(fname):
                vals[fname] = value
        months = infocom.get('warranty_duration') or 0
        start = vals.get('warranty_date') or (asset and asset.warranty_date)
        if start and months > 0 and empty('warranty_expiry_date'):
            vals['warranty_expiry_date'] = start + relativedelta(months=months)
        supplier = _ref_name(infocom.get('supplier'))
        if supplier and empty('vendor_id'):
            partner = self.env['res.partner'].sudo().search(
                [('name', '=ilike', escape_psql(supplier))], limit=1)
            if partner:
                vals['vendor_id'] = partner.id
        return vals

    def specs_text(self, components):
        lines = []
        cpus = components.get('Processor') or []
        names = sorted({(cpu.get('processor') or {}).get('designation') or '' for cpu in cpus} - {''})
        if names:
            cores = sum(cpu.get('nbcores') or 0 for cpu in cpus)
            threads = sum(cpu.get('nbthreads') or 0 for cpu in cpus)
            line = 'CPU: ' + ', '.join(names)
            if cores:
                line += f' ({cores} cores' + (f' / {threads} threads' if threads else '') + ')'
            lines.append(line)
        ram = sum(mem.get('size') or 0 for mem in components.get('Memory') or [])
        if ram:
            lines.append('RAM: ' + _format_size(ram))
        disks = [disk.get('capacity') for disk in components.get('HardDrive') or [] if disk.get('capacity')]
        if disks:
            lines.append('Storage: ' + ' + '.join(_format_size(size) for size in disks))
        return '\n'.join(lines) or False

    def product_for(self, item):
        name = ' '.join(filter(None, [_ref_name(item.get('manufacturer')),
                                      _ref_name(item.get('model'))]))
        if not name:
            return self.env['product.product']
        cache = self._cache.setdefault('products', {})
        if name not in cache:
            Product = self.env['product.product'].sudo()
            product = Product.search([('name', '=ilike', escape_psql(name))], limit=1)
            if not product and self.config.create_products and not self.dry_run:
                product = Product.create({
                    'name': name, 'type': 'consu', 'sale_ok': False, 'purchase_ok': True})
            cache[name] = product
        return cache[name]

    def employee_for_item(self, item, use_contact=False):
        """Employee for the GLPI user of an item; with ``use_contact`` also try
        the login reported by the GLPI Agent."""
        Employee = self.env['hr.employee'].sudo()
        UserMap = self.env['glpi.user.map'].sudo()
        user_ref = item.get('user') or {}
        if user_ref.get('id'):
            by_id, _by_login, _by_email = self.glpi_users()
            glpi_user = by_id.get(user_ref['id'])
            login = (glpi_user or {}).get('username') or user_ref.get('name')
            employee = UserMap._employee_for(login)
            for email in (glpi_user or {}).get('emails') or []:
                if employee or not email.get('email'):
                    continue
                employee = Employee.search(
                    [('work_email', '=ilike', escape_psql(email['email'].strip()))], limit=1)
            if not employee and login:
                employee = Employee.search(
                    [('user_id.login', '=ilike', escape_psql(_normalize_login(login)))], limit=1)
            if employee:
                return employee
        contact = _normalize_login(item.get('contact'))
        if use_contact and contact:
            return (UserMap._employee_for(contact)
                    or Employee.search([('user_id.login', '=ilike', escape_psql(contact))], limit=1)
                    or Employee.search([('work_email', '=ilike', escape_psql(contact) + '@%')], limit=1))
        return Employee

    def diff(self, asset, vals):
        changes = {}
        for fname, new in vals.items():
            field = asset._fields[fname]
            current = asset[fname]
            if field.type == 'many2many':
                changes[fname] = new
                continue
            if field.type == 'many2one':
                current = current.id
            elif field.type == 'date':
                new = fields.Date.to_date(new) if new else False
            elif field.type == 'datetime':
                new = fields.Datetime.to_datetime(new) if new else False
            elif field.type in ('float', 'monetary'):
                if float_compare(current or 0.0, new or 0.0, precision_digits=2):
                    changes[fname] = new
                continue
            if (current or False) != (new or False):
                changes[fname] = new
        return changes

    def track_glpi_state(self, asset, previous_state):
        if asset.glpi_sync_state == 'trashed' and previous_state != 'trashed':
            message = _("The GLPI item was moved to the GLPI trash.")
            asset.message_post(body=message)
            self.schedule_review(asset, _("Asset trashed in GLPI"), message)
            self.line('trashed', itemtype=asset.glpi_itemtype, asset=asset, message=message)
        elif asset.glpi_sync_state == 'linked' and previous_state in ('trashed', 'missing'):
            asset.message_post(body=_("The GLPI item is available again."))

    def mark_missing(self, asset):
        message = _("No longer returned by GLPI (purged, moved to another entity or trashed).")
        if not self.dry_run:
            asset.write({'glpi_sync_state': 'missing'})
            asset.message_post(body=message)
            self.schedule_review(asset, _("Asset missing in GLPI"), message)
        self.line('missing', itemtype=asset.glpi_itemtype, asset=asset, message=message)

    def check_custodian(self, asset, item):
        """Odoo is the custodian master: a different GLPI user is only flagged."""
        if asset.glpi_push_pending and self.config.write_back_enabled:
            return  # the pending push will overwrite the GLPI user
        if not (item.get('user') or {}).get('id'):
            if asset.glpi_custodian_mismatch:
                asset.write({'glpi_custodian_mismatch': False})
            return
        glpi_employee = self.employee_for_item(item)
        odoo_employee = asset._glpi_custodian()
        mismatch = glpi_employee != odoo_employee
        if mismatch == asset.glpi_custodian_mismatch:
            return
        asset.write({'glpi_custodian_mismatch': mismatch})
        if mismatch:
            message = _("GLPI user '%(glpi)s' differs from the Odoo custodian '%(odoo)s'.",
                        glpi=_ref_name(item.get('user')) or item['user']['id'],
                        odoo=odoo_employee.name or _('none'))
            asset.message_post(body=message)
            self.schedule_review(asset, _("GLPI custodian mismatch"), message)
            self.line('mismatch', item, asset.glpi_itemtype, asset, message=message)

    def schedule_review(self, asset, summary, note):
        if asset.activity_ids.filtered(lambda a: a.summary == summary):
            return
        user = self.config.responsible_user_id or self.env.ref('base.user_admin')
        asset.activity_schedule('mail.mail_activity_data_todo',
                                summary=summary, note=note, user_id=user.id)

    # =========================================================================
    # PUSH  (Odoo -> GLPI)
    # =========================================================================

    def push(self, export=None):
        if not self.config.write_back_enabled:
            return
        domain = [('glpi_id', '>', 0), ('glpi_push_pending', '=', True),
                  ('glpi_sync_state', '=', 'linked')]
        if self.assets is not None:
            domain.append(('id', 'in', self.assets.ids))
        for asset in self.Asset.search(domain):
            self.guarded(self.push_asset, asset, asset=asset)

        do_export = self.config.export_new_assets if export is None else export
        if do_export:
            domain = ['|', ('glpi_id', '=', False), ('glpi_id', '=', 0), ('state', '!=', 'disposed')]
            if self.assets is not None:
                domain.append(('id', 'in', self.assets.ids))
            else:
                domain.append(('serial_number', '!=', False))
            for asset in self.Asset.search(domain):
                self.guarded(self.export_asset, asset, asset=asset)

    def asset_payload(self, asset, warnings):
        cfg = self.config
        payload = {}
        if cfg.push_inventory_number and asset.name and asset.name != 'New':
            payload['otherserial'] = asset.name
        if cfg.push_custodian:
            employee = asset._glpi_custodian()
            if employee:
                glpi_user = self.glpi_user_for(employee)
                if glpi_user:
                    payload['user'] = {'id': glpi_user['id']}
                else:
                    warnings.append(_("no GLPI user found for %s", employee.name))
            elif asset.glpi_last_push:
                # Custodian removed in Odoo after a previous push. On the very
                # first push an existing GLPI user is kept and flagged instead.
                payload['user'] = {'id': 0}
        if cfg.push_status and asset.status:
            state_name = self.env['glpi.status.map'].sudo()._glpi_state_for(asset.status)
            if state_name:
                state_id = self.named_ids('states', self.client.list_states, _('statuses')).get(
                    state_name.strip().lower())
                if state_id:
                    payload['status'] = {'id': state_id}
                else:
                    warnings.append(_("GLPI status '%s' not found", state_name))
        if cfg.push_location and asset.location_description:
            location_id = self.named_ids('locations', self.client.list_locations, _('locations')).get(
                asset.location_description.strip().lower())
            if location_id:
                payload['location'] = {'id': location_id}
            else:
                warnings.append(_("GLPI location '%s' not found", asset.location_description))
        return payload

    def infocom_payload(self, asset, warnings):
        payload = {}
        if asset.amount:
            payload['value'] = asset.amount
        for fname, glpi_key in (('invoice_date', 'date_buy'),
                                ('capitalized_date', 'date_use'),
                                ('warranty_date', 'date_warranty'),
                                ('disposal_date', 'date_decommission')):
            if asset[fname]:
                payload[glpi_key] = fields.Date.to_string(asset[fname])
        if (asset.warranty_date and asset.warranty_expiry_date
                and asset.warranty_expiry_date > asset.warranty_date):
            delta = relativedelta(asset.warranty_expiry_date, asset.warranty_date)
            payload['warranty_duration'] = delta.years * 12 + delta.months
        if asset.invoice_id:
            payload['invoice_number'] = asset.invoice_id.name
        if asset.vendor_id:
            supplier_id = self.named_ids('suppliers', self.client.list_suppliers, _('suppliers')).get(
                asset.vendor_id.name.strip().lower())
            if supplier_id:
                payload['supplier'] = {'id': supplier_id}
            else:
                warnings.append(_("GLPI supplier '%s' not found", asset.vendor_id.name))
        if not payload and not asset.glpi_infocom_id:
            return {}  # nothing financial to say: do not create an empty Infocom
        if asset.name and asset.name != 'New':
            payload['immo_number'] = asset.name
        return payload

    def glpi_user_for(self, employee):
        _by_id, by_login, by_email = self.glpi_users()
        login = self.env['glpi.user.map'].sudo()._login_for(employee)
        if login and _normalize_login(login) in by_login:
            return by_login[_normalize_login(login)]
        for email in (employee.work_email, employee.user_id.email, employee.user_id.login):
            if email and email.strip().lower() in by_email:
                return by_email[email.strip().lower()]
        if employee.user_id.login:
            return by_login.get(_normalize_login(employee.user_id.login))
        return None

    def push_infocom(self, asset, payload):
        itemtype, glpi_id = asset.glpi_itemtype, asset.glpi_id
        if not asset.glpi_infocom_id:
            existing = self.client.get_infocom(itemtype, glpi_id)
            if existing:
                asset.write({'glpi_infocom_id': existing['id']})
        if asset.glpi_infocom_id:
            self.client.update_infocom(itemtype, glpi_id, payload)
        else:
            asset.write({'glpi_infocom_id': self.client.create_infocom(itemtype, glpi_id, payload) or 0})

    def push_asset(self, asset):
        warnings = []
        payload = self.asset_payload(asset, warnings)
        if payload:
            self.client.update_asset(asset.glpi_itemtype, asset.glpi_id, payload)
        infocom = self.config.push_financials and self.infocom_payload(asset, warnings)
        if infocom:
            self.push_infocom(asset, infocom)
        vals = {'glpi_push_pending': False, 'glpi_last_push': fields.Datetime.now()}
        if 'user' in payload:
            vals['glpi_custodian_mismatch'] = False
        asset.write(vals)
        pushed = sorted(payload) + (['infocom'] if infocom else [])
        message = ', '.join(pushed) or _('nothing to push')
        if warnings:
            message += ' — ' + '; '.join(warnings)
        self.line('pushed', asset=asset, message=message, level='warning' if warnings else 'info')

    def export_asset(self, asset):
        if not asset.serial_number:
            raise GlpiError(_("A serial number is required to create the asset in GLPI "
                              "(the GLPI Agent matches computers by serial)."))
        itemtype = (self.env['glpi.type.map'].sudo()._itemtype_for_asset_type(asset.asset_type_id)
                    or self.config.export_itemtype or 'Computer')
        warnings = []
        payload = dict(self.asset_payload(asset, warnings),
                       name=asset.asset_name, serial=asset.serial_number)
        glpi_id = self.client.create_asset(itemtype, payload)
        if not glpi_id:
            raise GlpiError(_("GLPI did not return the id of the new item."))
        asset.write({
            'glpi_id': glpi_id,
            'glpi_itemtype': itemtype,
            'glpi_sync_state': 'linked',
            'glpi_name': asset.asset_name,
            'glpi_push_pending': False,
            'glpi_last_push': fields.Datetime.now(),
        })
        infocom = self.config.push_financials and self.infocom_payload(asset, warnings)
        if infocom:
            self.push_infocom(asset, infocom)
        asset.message_post(body=_("Created in GLPI as %(itemtype)s #%(id)s.",
                                  itemtype=itemtype, id=glpi_id))
        message = _("%(itemtype)s #%(id)s", itemtype=itemtype, id=glpi_id)
        if warnings:
            message += ' — ' + '; '.join(warnings)
        self.line('exported', asset=asset, message=message, level='warning' if warnings else 'info')
