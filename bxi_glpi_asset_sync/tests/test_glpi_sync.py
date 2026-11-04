# -*- coding: utf-8 -*-
import copy
from datetime import date
from unittest.mock import patch

from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.bxi_glpi_asset_sync.models.glpi_client import GlpiError


class FakeGlpiClient:
    """In-memory stand-in for GlpiClient, recording every write."""

    def __init__(self):
        self.assets = {'Computer': [], 'Printer': []}
        self.infocoms = {}
        self.components = {}
        self.users = []
        self.states = []
        self.locations = []
        self.suppliers = []
        self.updates = []
        self.created = []
        self.infocom_writes = []
        self._next_id = 1000

    def list_assets(self, itemtype):
        return copy.deepcopy(self.assets.get(itemtype, []))

    def request(self, method, path, params=None, payload=None, allow_404=False):
        itemtype, glpi_id = path.split('/')[2], int(path.split('/')[3])
        for item in self.assets.get(itemtype, []):
            if item['id'] == glpi_id:
                return copy.deepcopy(item)
        if allow_404:
            return None
        raise GlpiError('not found', 404)

    def get_infocom(self, itemtype, glpi_id):
        return copy.deepcopy(self.infocoms.get((itemtype, glpi_id)))

    def get_components(self, glpi_id, kind):
        return copy.deepcopy(self.components.get(glpi_id, {}).get(kind, []))

    def list_users(self):
        return copy.deepcopy(self.users)

    def list_states(self):
        return copy.deepcopy(self.states)

    def list_locations(self):
        return copy.deepcopy(self.locations)

    def list_suppliers(self):
        return copy.deepcopy(self.suppliers)

    def update_asset(self, itemtype, glpi_id, payload):
        self.updates.append((itemtype, glpi_id, payload))
        return {}

    def create_asset(self, itemtype, payload):
        self._next_id += 1
        self.created.append((itemtype, payload))
        return self._next_id

    def create_infocom(self, itemtype, glpi_id, payload):
        self.infocom_writes.append(('create', itemtype, glpi_id, payload))
        self.infocoms[(itemtype, glpi_id)] = dict(payload, id=500 + glpi_id)
        return 500 + glpi_id

    def update_infocom(self, itemtype, glpi_id, payload):
        self.infocom_writes.append(('update', itemtype, glpi_id, payload))
        return {}


def computer(glpi_id, name, serial, **extra):
    item = {
        'id': glpi_id,
        'name': name,
        'serial': serial,
        'otherserial': '',
        'is_template': False,
        'is_deleted': False,
        'manufacturer': {'id': 1, 'name': 'Dell Inc.'},
        'model': {'id': 2, 'name': 'Latitude 5410'},
        'type': {'id': 1, 'name': 'Notebook'},
        'status': None,
        'location': None,
        'user': None,
        'contact': '',
        'uuid': f'uuid-{glpi_id}',
        'date_mod': '2026-10-28T09:19:00+05:30',
        'last_inventory_update': '2026-10-28T09:19:00+05:30',
    }
    item.update(extra)
    return item


@tagged('post_install', '-at_install')
class TestGlpiSync(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Asset = cls.env['asset.management']
        cls.laptop_type = cls.env['asset.type'].create({
            'name': 'Laptop',
            'depreciation_frequency': 'yearly',
            'depreciation_method': 'straight_line',
            'depreciation_basis': 'real_value',
        })
        cls.env['glpi.type.map'].create({
            'glpi_itemtype': 'Computer',
            'glpi_type_name': 'Notebook',
            'asset_type_id': cls.laptop_type.id,
        })
        cls.asha = cls.env['hr.employee'].create({'name': 'Asha', 'work_email': 'asha@bxitech.com'})
        cls.ravi = cls.env['hr.employee'].create({'name': 'Ravi', 'work_email': 'ravi@bxitech.com'})
        cls.config = cls.env['glpi.config'].create({
            'name': 'Test GLPI',
            'base_url': 'https://glpi.test',
            'client_id': 'cid',
            'client_secret': 'secret',
            'username': 'odoo',
            'password': 'pwd',
            'glpi_tz': 'Asia/Kolkata',
        })
        cls.existing = cls.Asset.create({
            'asset_name': 'Dell Latitude (old record)',
            'serial_number': 'hqlp793',
            'amount': 1000.0,
        })

    def setUp(self):
        super().setUp()
        self.fake = FakeGlpiClient()
        self.fake.users = [
            {'id': 7, 'username': 'asha', 'emails': [{'email': 'asha@bxitech.com'}]},
            {'id': 8, 'username': 'ravi', 'emails': [{'email': 'Ravi@BXITECH.com'}]},
        ]
        self.fake.assets['Computer'] = [
            computer(1, 'BXITECH-LT-0001', 'HQLP793'),
            computer(2, 'BXITECH-LT-0013', '6NPVL84', user={'id': 7, 'name': 'asha'}),
            computer(3, "X' AND SLEEP(6)-- -", ''),
            computer(4, 'poc_c7fa1a07', 'POC123'),
            computer(5, 'Template laptop', 'TPL1', is_template=True),
        ]
        self.fake.infocoms[('Computer', 1)] = {'id': 41, 'value': 99999.0, 'date_buy': '2020-01-01'}
        self.fake.infocoms[('Computer', 2)] = {
            'id': 42, 'value': 55000.0, 'date_buy': '2025-04-01', 'date_use': '2025-04-05',
            'date_warranty': '2025-04-01', 'warranty_duration': 36,
        }
        self.fake.components[2] = {
            'Processor': [{'processor': {'designation': 'Intel(R) Core(TM) i3-1305U'},
                           'nbcores': 5, 'nbthreads': 6}],
            'Memory': [{'size': 8192}, {'size': 8192}],
            'HardDrive': [{'capacity': 512000}],
        }
        patcher = patch.object(self.registry['glpi.config'], '_glpi_client',
                               lambda config: self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _sync(self, **kwargs):
        log = self.config._run_sync(**kwargs)
        self.assertNotEqual(log.state, 'failed', log.message)
        return log

    def _glpi_asset(self, glpi_id):
        return self.Asset.search([('glpi_itemtype', '=', 'Computer'), ('glpi_id', '=', glpi_id)])

    # ─── Pull ────────────────────────────────────────────────────────────────

    def test_dry_run_writes_nothing(self):
        log = self._sync(dry_run=True)
        self.assertFalse(self.Asset.search([('glpi_id', '>', 0)]))
        self.assertEqual(log.created_count, 1)
        self.assertEqual(log.linked_count, 1)
        self.assertEqual(log.skipped_count, 3)
        self.assertEqual(len(log.line_ids.filtered(lambda l: l.action == 'skipped')), 3)

    def test_pull_creates_and_links(self):
        log = self._sync(push=False)
        self.assertEqual((log.created_count, log.linked_count, log.skipped_count), (1, 1, 3))

        linked = self._glpi_asset(1)
        self.assertEqual(linked, self.existing, "existing asset must be linked by serial")
        self.assertEqual(linked.serial_number, 'HQLP793', "GLPI is the serial master")
        self.assertTrue(linked.glpi_push_pending)

        created = self._glpi_asset(2)
        self.assertEqual(created.asset_name, 'BXITECH-LT-0013')
        self.assertEqual(created.state, 'draft')
        self.assertEqual(created.asset_type_id, self.laptop_type)
        self.assertEqual(created.amount, 55000.0)
        self.assertEqual(created.invoice_date, date(2025, 4, 1))
        self.assertEqual(created.warranty_expiry_date, date(2028, 4, 1))
        self.assertEqual(created.employee_id, self.asha)
        self.assertEqual(created.status, 'assign')
        self.assertEqual(created.transfer_ids.transfer_employee_id, self.asha)
        self.assertIn('CPU: Intel(R) Core(TM) i3-1305U (5 cores / 6 threads)', created.glpi_specs)
        self.assertIn('RAM: 16 GB', created.glpi_specs)
        self.assertEqual(created.glpi_date_mod.strftime('%H:%M'), '03:49', "stored in UTC")

    def test_second_run_is_idempotent(self):
        self._sync(push=False)
        log = self._sync(push=False)
        self.assertEqual((log.created_count, log.linked_count, log.updated_count), (0, 0, 0))
        self.assertEqual(log.unchanged_count, 2)

    def test_confirmed_asset_financials_untouched(self):
        self.existing.write({'state': 'confirmed'})
        self._sync(push=False)
        self.assertEqual(self.existing.amount, 1000.0)
        self.assertFalse(self.existing.invoice_date)

    def test_glpi_change_updates_glpi_owned_fields(self):
        self._sync(push=False)
        self.fake.assets['Computer'][0].update(
            name='BXITECH-LT-0001-RENAMED', date_mod='2026-10-29T10:00:00+05:30')
        log = self._sync(push=False)
        self.assertEqual(log.updated_count, 1)
        self.assertEqual(self.existing.glpi_name, 'BXITECH-LT-0001-RENAMED')
        self.assertEqual(self.existing.asset_name, 'Dell Latitude (old record)',
                         "asset name is only taken from GLPI on create")

    def test_custodian_mismatch_is_only_flagged(self):
        self._sync(push=False)
        asset = self._glpi_asset(2)
        self.fake.assets['Computer'][1].update(
            user={'id': 8, 'name': 'ravi'}, date_mod='2026-10-29T10:00:00+05:30')
        log = self._sync(push=False)
        self.assertTrue(asset.glpi_custodian_mismatch)
        self.assertEqual(asset._glpi_custodian(), self.asha, "Odoo stays the custodian master")
        self.assertEqual(log.line_ids.filtered(lambda l: l.action == 'mismatch').asset_id, asset)
        self.assertTrue(asset.activity_ids.filtered(lambda a: a.summary == 'GLPI custodian mismatch'))

    def test_missing_item_is_flagged_not_disposed(self):
        self._sync(push=False)
        self.fake.assets['Computer'] = self.fake.assets['Computer'][1:]
        log = self._sync(push=False)
        self.assertEqual(self.existing.glpi_sync_state, 'missing')
        self.assertNotEqual(self.existing.state, 'disposed')
        self.assertEqual(log.missing_count, 1)

    def test_conflict_when_several_assets_match(self):
        self.Asset.create({'asset_name': 'Duplicate', 'serial_number': 'HQLP793'})
        log = self._sync(push=False)
        self.assertEqual(log.conflict_count, 1)
        self.assertFalse(self._glpi_asset(1))

    # ─── Push ────────────────────────────────────────────────────────────────

    def test_odoo_change_queues_push(self):
        self._sync(push=False)
        self.existing.with_context(glpi_sync=True).write({'glpi_push_pending': False})
        self.existing.write({'location_description': 'Floor 3'})
        self.assertTrue(self.existing.glpi_push_pending)
        self.existing.with_context(glpi_sync=True).write({'glpi_push_pending': False})
        self.env['asset.transfer.entry'].create({
            'asset_id': self.existing.id, 'transfer_employee_id': self.ravi.id, 'status': 'assigned'})
        self.assertTrue(self.existing.glpi_push_pending)

    def test_push_is_skipped_when_write_back_disabled(self):
        self._sync()
        self.assertFalse(self.fake.updates)
        self.assertTrue(self.existing.glpi_push_pending)

    def test_push_odoo_owned_fields(self):
        self.config.write_back_enabled = True
        self.fake.locations = [{'id': 3, 'name': 'Floor 3', 'completename': 'HQ > Floor 3'}]
        self.existing.write({'location_description': 'floor 3', 'invoice_date': date(2024, 6, 1)})
        self.env['asset.transfer.entry'].create({
            'asset_id': self.existing.id, 'transfer_employee_id': self.ravi.id, 'status': 'assigned'})
        log = self._sync()
        self.assertEqual(log.error_count, 0, log.line_ids.mapped('message'))

        payloads = {glpi_id: payload for _itemtype, glpi_id, payload in self.fake.updates}
        self.assertEqual(payloads[1], {
            'otherserial': self.existing.name,
            'user': {'id': 8},
            'location': {'id': 3},
        })
        self.assertEqual(payloads[2]['user'], {'id': 7})
        infocom = [w for w in self.fake.infocom_writes if w[2] == 1]
        self.assertEqual(infocom[0][0], 'update', "existing GLPI Infocom must be updated")
        self.assertEqual(infocom[0][3]['value'], 1000.0)
        self.assertEqual(infocom[0][3]['date_buy'], '2024-06-01')
        self.assertFalse(self.existing.glpi_push_pending)
        self.assertTrue(self.existing.glpi_last_push)

        # nothing changed in Odoo: the next run pushes nothing
        self.fake.updates.clear()
        self._sync()
        self.assertFalse(self.fake.updates)

    def test_first_push_keeps_glpi_user_when_no_odoo_custodian(self):
        self.config.write_back_enabled = True
        self.fake.assets['Computer'][0]['user'] = {'id': 7, 'name': 'asha'}
        self._sync()
        payload = next(p for _t, glpi_id, p in self.fake.updates if glpi_id == 1)
        self.assertNotIn('user', payload)

    def test_export_odoo_only_asset(self):
        self.config.write_back_enabled = True
        asset = self.Asset.create({
            'asset_name': 'Spare laptop', 'serial_number': 'NEW123',
            'asset_type_id': self.laptop_type.id, 'amount': 42000.0})
        asset.action_glpi_export()
        self.assertEqual(self.fake.created[0][0], 'Computer')
        self.assertEqual(self.fake.created[0][1]['serial'], 'NEW123')
        self.assertTrue(asset.glpi_id)
        self.assertEqual(asset.glpi_sync_state, 'linked')
        self.assertEqual(self.fake.infocom_writes[0][0], 'create')

    def test_export_requires_serial(self):
        self.config.write_back_enabled = True
        asset = self.Asset.create({'asset_name': 'No serial'})
        asset.action_glpi_export()
        self.assertFalse(asset.glpi_id)
        self.assertFalse(self.fake.created)

    # ─── Security ────────────────────────────────────────────────────────────

    def test_synced_assets_visible_to_asset_users(self):
        self._sync(push=False)
        user = new_test_user(self.env, login='asset_user_glpi',
                             groups='base.group_user,asset_management.assets_user_group')
        visible = self.Asset.with_user(user).search([('glpi_id', '>', 0)])
        self.assertEqual(len(visible), 2)
