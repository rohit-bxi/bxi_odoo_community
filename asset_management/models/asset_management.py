# -*- coding: utf-8 -*-
from odoo import models, fields, api, _, exceptions
from dateutil.relativedelta import relativedelta
from datetime import datetime, timedelta
import base64
import io
import os
import textwrap
from PIL import Image, ImageDraw, ImageFont
from odoo.exceptions import UserError, ValidationError

ORANGE = (255, 140, 0)

try:
    import qrcode
except ImportError:
    qrcode = None


class AssetType(models.Model):
    _name = 'asset.type'
    _description = 'Asset Type'

    name = fields.Char(string='Name', required=True)
    color = fields.Integer(string='Color Index', help="Color index for this asset type")

    # Depreciation Settings
    depreciation_frequency = fields.Selection([
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
        ('days', 'Days')
    ], string='Depreciation Frequency', required=True,
        help="How often depreciation is calculated (Yearly, Monthly, or Daily)")

    depreciation_method = fields.Selection([
        ('fix', 'Fixed Amount'),
        ('percentage', 'Percentage'),
        ('straight_line', 'Straight-Line (SLM)'),
        ('declining_balance', 'Declining Balance'),
    ], string='Depreciation Method', required=True,
        help="Method used to calculate depreciation amount")

    depreciation_rate = fields.Float(string='Depreciation Rate',
        help="The percentage or fixed amount used to calculate depreciation")
    depreciation_start_delay = fields.Integer(string='Depreciation Start Delay',
        help="Time duration before depreciation begins after asset acquisition")
    depreciation_basis = fields.Selection([
        ('real_value', 'Purchase Price'),
        ('depreciation_value', 'Book Price')
    ], string='Depreciation Basis', required=True,
        help="Whether depreciation is applied to the adjusted or original value")
    maximum_depreciation_entries = fields.Integer(string="Maximum Depreciation Entries",
        help="Maximum number of depreciation entries allowed")
    salvage_value_rate = fields.Float(string='Salvage Value Rate (%)',
        help="Percentage of purchase price retained as salvage/residual value")

    # Default Accounting Accounts (inherited by assets of this type)
    fixed_asset_account_id = fields.Many2one('account.account',
        string='Fixed Asset Account',
        help="Balance sheet account for capitalizing the asset (e.g., 16XX Fixed Assets)")
    depreciation_expense_account_id = fields.Many2one('account.account',
        string='Depreciation Expense Account',
        help="P&L account for depreciation charges (e.g., 68XX Depreciation)")
    accumulated_depreciation_account_id = fields.Many2one('account.account',
        string='Accumulated Depreciation Account',
        help="Balance sheet contra account for accumulated depreciation (e.g., 28XX)")
    asset_journal_id = fields.Many2one('account.journal',
        string='Asset Journal',
        domain=[('type', 'in', ['general', 'purchase'])],
        help="Accounting journal for asset and depreciation entries")
    asset_clearing_account_id = fields.Many2one('account.account',
        string='Asset Clearing Account',
        help="Account credited when asset is acquired (e.g., Accounts Payable or Suspense)")


class AssetTag(models.Model):
    _name = 'asset.tag'
    _description = 'Asset Tag'

    name = fields.Char(string='Name', required=True)
    color = fields.Integer(string='Color Index')

    _sql_constraints = [
        ('name_uniq', 'unique (name)', "Tag name already exists!"),
    ]


class Asset(models.Model):
    _name = 'asset.management'
    _description = 'Asset Management'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    # ─── Basic Information ───────────────────────────────────────────────────
    name = fields.Char(string="Asset Reference", required=True, copy=False,
                       readonly=True, default=lambda self: _('New'), tracking=True)
    asset_name = fields.Char(string="Asset Name", required=True,
                              help="Descriptive name of the asset")
    barcode = fields.Char(string="Barcode", copy=False,
                          help="Barcode for asset identification and scanning")
    serial_number = fields.Char(string="Serial Number", copy=False,
                                help="Manufacturer serial number of the asset")
    product_id = fields.Many2one('product.product', string="Associated Product",
                                  help="Select the product used in this asset")
    asset_type_id = fields.Many2one('asset.type', string="Asset Type", tracking=True,
                                     help="Classification of the asset")
    asset_image = fields.Image(string="Asset Photo", max_width=1024, max_height=1024)

    # ─── Asset Details ────────────────────────────────────────────────────────
    asset_condition = fields.Selection([
        ('new', 'New'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('poor', 'Poor'),
        ('damaged', 'Damaged'),
    ], string='Condition', default='new', tracking=True)
    department_id = fields.Many2one('hr.department', string="Department",
                                     help="Department responsible for this asset")
    employee_id = fields.Many2one('hr.employee', string="Current Custodian",
                                   help="Employee currently holding/responsible for this asset",
                                   tracking=True)
    location_description = fields.Char(string="Location/Room",
                                       help="Physical location of the asset (e.g., Server Room, Floor 3)")
    asset_configuration = fields.Text(string='Asset Configuration / Specs')

    # ─── Model Type and Stock Management ─────────────────────────────────────
    model_type = fields.Selection([
        ('single', 'Single Asset'),
        ('multiple', 'Multiple Assets')
    ], string="Model Type", default='single', required=True,
        help="Single: Unique asset with specific tracking. Multiple: Assets with stock management")

    initial_stock = fields.Integer(string="Initial Stock", default=1,
                                   help="Initial quantity of this asset")
    current_stock = fields.Integer(string="Current Stock",
                                   compute='_compute_current_stock', store=True,
                                   help="Current available quantity")
    active_transfers = fields.Integer(string="Active Transfers",
                                      compute='_compute_active_transfers', store=True,
                                      help="Number of assets currently assigned")

    # ─── State / Status ───────────────────────────────────────────────────────
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('disposed', 'Disposed'),
    ], string='Accounting State', default='draft', tracking=True,
        help="Draft: not yet capitalized. Confirmed: asset capitalized and in use. Disposed: written off.")

    status = fields.Selection([
        ('assign', 'Assigned'),
        ('return', 'Returned'),
        ('on_hold', 'On Hold'),
        ('in_warehouse', 'In Warehouse'),
        ('repair', 'Repair'),
        ('destroyed', 'Destroyed'),
    ], string="Operational Status", default="in_warehouse", tracking=True)

    # ─── Financial Information ────────────────────────────────────────────────
    amount = fields.Float(string="Purchase Cost", help="Initial cost of acquiring the asset",
                          tracking=True)
    salvage_value = fields.Float(string="Salvage / Residual Value",
                                  help="Estimated scrap/residual value at end of useful life")
    depreciable_amount = fields.Float(string="Depreciable Amount",
                                       compute='_compute_depreciable_amount', store=True,
                                       help="Purchase Cost minus Salvage Value")
    useful_life_years = fields.Integer(string="Useful Life (Years)", default=5,
                                        help="Expected useful life in years (for SLM)")
    invoice_date = fields.Date(string="Purchase / Invoice Date",
                                help="Date when the asset was purchased or acquired")
    capitalized_date = fields.Date(string="Capitalization Date",
                                    help="Date the asset was put into service")
    invoice_id = fields.Many2one('account.move', string="Purchase Invoice")

    # ─── Computed Financial Fields ────────────────────────────────────────────
    current_amount = fields.Float(string="Net Book Value (NBV)",
                                   compute="_compute_net_book_value", store=True,
                                   help="Current value: Purchase Cost - Accumulated Depreciation - Salvage")
    total_depreciation_amount = fields.Float(string="Accumulated Depreciation",
                                              compute='_compute_total_depreciation_amount',
                                              store=True,
                                              help="Total depreciation applied to date")
    total_maintenance_amount = fields.Float(string="Total Maintenance Cost",
                                             compute='_compute_total_maintenance_amount',
                                             store=True)
    depreciation_percentage = fields.Float(string="Depreciation %",
                                            compute='_compute_depreciation_percentage',
                                            store=True,
                                            help="Percentage of asset cost depreciated so far")


    # ─── Accounting Integration ───────────────────────────────────────────────
    # NOTE: We store the account.asset record ID as Integer (not Many2one) to
    # avoid an AssertionError at startup when the 'account_asset' module is not
    # installed. We use self.env.get('account.asset') at runtime for safety.
    account_asset_id_int = fields.Integer(
        string="Fixed Asset Record ID", copy=False, readonly=True,
        help="ID of the linked record in Odoo's account.asset (Fixed Assets module)")
    account_asset_display = fields.Char(
        string="Fixed Asset Ref.", compute='_compute_account_asset_display',
        store=False, readonly=True)

    fixed_asset_account_id = fields.Many2one('account.account',
        string='Fixed Asset Account',
        help="Balance sheet account for capitalizing the asset")
    depreciation_expense_account_id = fields.Many2one('account.account',
        string='Depreciation Expense Account',
        help="P&L account for depreciation charges")
    accumulated_depreciation_account_id = fields.Many2one('account.account',
        string='Accumulated Depreciation Account',
        help="Balance sheet contra account for accumulated depreciation")
    asset_journal_id = fields.Many2one('account.journal',
        string='Asset Journal',
        domain=[('type', 'in', ['general', 'purchase'])],
        help="Accounting journal for asset and depreciation entries")
    asset_clearing_account_id = fields.Many2one('account.account',
        string='Asset Clearing Account',
        help="Account credited on asset acquisition (e.g., Accounts Payable)")

    # Journal entries
    acquisition_move_id = fields.Many2one('account.move',
        string='Acquisition Journal Entry', copy=False, readonly=True)
    disposal_move_id = fields.Many2one('account.move',
        string='Disposal Journal Entry', copy=False, readonly=True)
    disposal_date = fields.Date(string="Disposal Date", copy=False, readonly=True)

    # ─── Warranty & Insurance ─────────────────────────────────────────────────
    expired_warranty_date = fields.Date(string="Asset Expiry Date")
    warranty_date = fields.Date(string="Warranty Start Date")
    warranty_expiry_date = fields.Date(string="Warranty Expiry Date")
    insurance_policy_no = fields.Char(string="Insurance Policy No.")
    insurance_provider = fields.Char(string="Insurance Provider")
    insurance_expiry_date = fields.Date(string="Insurance Expiry Date")
    expected_replacement_date = fields.Date(string="Expected Replacement Date")

    # ─── Vendor Info ──────────────────────────────────────────────────────────
    vendor_id = fields.Many2one('asset.vendor', string="Associated Vendor")

    # ─── Depreciation Settings ────────────────────────────────────────────────
    depreciation_apply = fields.Boolean(string="Enable Depreciation",
                                         help="Check to apply depreciation for this asset")
    last_depreciation_date = fields.Date(string="Last Depreciation Date", readonly=True)

    # ─── Related Documents ────────────────────────────────────────────────────
    document_ids = fields.Many2many('ir.attachment', string="Asset Documentation")
    tag_ids = fields.Many2many('asset.tag', string='Tags',
                                help="Categorize assets with tags")

    # ─── Related Entries (One2many) ───────────────────────────────────────────
    transfer_ids = fields.One2many('asset.transfer.entry', 'asset_id',
                                    string="Transfer Entries")
    maintenance_ids = fields.One2many('asset.maintenance.entry', 'asset_id',
                                       string="Maintenance Entries")
    depreciation_ids = fields.One2many('asset.depreciation.entry', 'asset_id',
                                        string="Depreciation Entries")

    # ─── Smart Button Counts ──────────────────────────────────────────────────
    transfer_count = fields.Integer(string='Transfer Count',
                                    compute='_compute_all_count', store=True)
    maintenance_count = fields.Integer(string='Maintenance Count',
                                       compute='_compute_all_count', store=True)
    depreciation_count = fields.Integer(string='Depreciation Count',
                                         compute='_compute_all_count', store=True)
    journal_entry_count = fields.Integer(string='Journal Entries',
                                          compute='_compute_journal_entry_count')

    # ─── Computed Utility Fields ──────────────────────────────────────────────
    assigned_user = fields.Char(string="Assigned To",
                                 compute='_compute_assigned_user', store=True)
    assign_by = fields.Char(string="Assigned By",
                             compute='_compute_assigned_user', store=True)
    remaining_warranty = fields.Char(string="Remaining Warranty",
                                      compute="_compute_months_left", store=True)
    warranty_status = fields.Char(string='Warranty Status')

    # ─── QR Code Fields ───────────────────────────────────────────────────────
    qr_payload = fields.Char(string="QR Payload", copy=False, readonly=True)
    qr_image = fields.Binary(string="QR Code", copy=False, readonly=True, attachment=True)
    qr_filename = fields.Char(string="QR Filename", copy=False, readonly=True)
    qr_generated_on = fields.Datetime(string="QR Generated On", copy=False, readonly=True)

    # ─── Currency (for monetary widget) ──────────────────────────────────────
    currency_id = fields.Many2one('res.currency', string='Currency',
                                   default=lambda self: self.env.company.currency_id)

    # =========================================================================
    # COMPUTE METHODS
    # =========================================================================

    @api.depends('amount', 'salvage_value')
    def _compute_depreciable_amount(self):
        for rec in self:
            rec.depreciable_amount = max(0.0, rec.amount - rec.salvage_value)

    @api.depends('amount', 'total_depreciation_amount', 'salvage_value')
    def _compute_net_book_value(self):
        for rec in self:
            rec.current_amount = max(
                rec.salvage_value,
                rec.amount - rec.total_depreciation_amount
            )

    @api.depends('depreciation_ids.depreciation_amount', 'depreciation_ids.state')
    def _compute_total_depreciation_amount(self):
        for rec in self:
            posted = rec.depreciation_ids.filtered(lambda d: d.state == 'posted')
            rec.total_depreciation_amount = sum(posted.mapped('depreciation_amount'))

    @api.depends('maintenance_ids.maintenance_amount')
    def _compute_total_maintenance_amount(self):
        for rec in self:
            rec.total_maintenance_amount = sum(
                rec.maintenance_ids.mapped('maintenance_amount'))

    @api.depends('total_depreciation_amount', 'amount', 'depreciable_amount')
    def _compute_depreciation_percentage(self):
        for rec in self:
            if rec.amount and rec.depreciable_amount:
                rec.depreciation_percentage = (
                    rec.total_depreciation_amount / rec.depreciable_amount) * 100
            else:
                rec.depreciation_percentage = 0.0

    @api.depends('transfer_ids', 'transfer_ids.status', 'transfer_ids.stock_qty')
    def _compute_active_transfers(self):
        for rec in self:
            assigned = rec.transfer_ids.filtered(lambda t: t.status == 'assigned')
            rec.active_transfers = sum(assigned.mapped('stock_qty'))

    @api.depends('initial_stock', 'active_transfers')
    def _compute_current_stock(self):
        for rec in self:
            rec.current_stock = rec.initial_stock - rec.active_transfers

    @api.depends('transfer_ids', 'maintenance_ids', 'depreciation_ids')
    def _compute_all_count(self):
        for rec in self:
            rec.transfer_count = len(rec.transfer_ids)
            rec.maintenance_count = len(rec.maintenance_ids)
            rec.depreciation_count = len(rec.depreciation_ids)

    def _compute_journal_entry_count(self):
        for rec in self:
            moves = self.env['account.move'].search([
                ('ref', 'like', rec.name),
                ('move_type', '=', 'entry'),
            ])
            count = len(moves)
            if rec.acquisition_move_id:
                count += 1
            if rec.disposal_move_id:
                count += 1
            rec.journal_entry_count = count

    @api.depends('expired_warranty_date')
    def _compute_months_left(self):
        today = fields.Date.today()
        for rec in self:
            if rec.expired_warranty_date:
                if rec.expired_warranty_date < today:
                    rec.remaining_warranty = 'Expired'
                    rec.warranty_status = 'expired'
                elif rec.expired_warranty_date == today:
                    rec.remaining_warranty = 'Today'
                    rec.warranty_status = 'danger'
                else:
                    rd = relativedelta(rec.expired_warranty_date, today)
                    total_months = rd.years * 12 + rd.months + (rd.days / 30)
                    if total_months > 6:
                        rec.warranty_status = 'success'
                    elif 3 <= total_months <= 6:
                        rec.warranty_status = 'warning'
                    else:
                        rec.warranty_status = 'danger'
                    parts = []
                    if rd.years > 0:
                        parts.append(f"{rd.years} year{'s' if rd.years > 1 else ''}")
                    elif rd.months > 0:
                        parts.append(f"{rd.months} month{'s' if rd.months > 1 else ''}")
                    elif rd.days > 0:
                        parts.append(f"{rd.days} day{'s' if rd.days > 1 else ''}")
                    rec.remaining_warranty = ', '.join(parts)
            else:
                rec.remaining_warranty = 'No warranty'
                rec.warranty_status = 'expired'

    @api.depends('transfer_ids')
    def _compute_assigned_user(self):
        for rec in self:
            if rec.transfer_ids:
                last = rec.transfer_ids.filtered(
                    lambda t: t.status == 'assigned')
                if last:
                    last = last[-1]
                    rec.assigned_user = last.transfer_employee_id.name or ''
                    rec.assign_by = last.assign_by.name or ''
                else:
                    last = rec.transfer_ids[-1]
                    rec.assigned_user = last.transfer_employee_id.name or ''
                    rec.assign_by = last.assign_by.name or ''
            else:
                rec.assigned_user = ''
                rec.assign_by = ''

    # =========================================================================
    # ON-CHANGE — Auto-fill accounts from Asset Type
    # =========================================================================

    @api.onchange('asset_type_id')
    def _onchange_asset_type(self):
        if self.asset_type_id:
            t = self.asset_type_id
            if t.fixed_asset_account_id:
                self.fixed_asset_account_id = t.fixed_asset_account_id
            if t.depreciation_expense_account_id:
                self.depreciation_expense_account_id = t.depreciation_expense_account_id
            if t.accumulated_depreciation_account_id:
                self.accumulated_depreciation_account_id = t.accumulated_depreciation_account_id
            if t.asset_journal_id:
                self.asset_journal_id = t.asset_journal_id
            if t.asset_clearing_account_id:
                self.asset_clearing_account_id = t.asset_clearing_account_id

    def _compute_account_asset_display(self):
        """Show the linked account.asset display name (safe: no Many2one dependency)."""
        AccountAsset = self.env.get('account.asset')
        for rec in self:
            if rec.account_asset_id_int and AccountAsset:
                try:
                    record = AccountAsset.browse(rec.account_asset_id_int).exists()
                    rec.account_asset_display = record.display_name if record else ''
                except Exception:
                    rec.account_asset_display = str(rec.account_asset_id_int)
            else:
                rec.account_asset_display = ''

    # =========================================================================
    # CREATE / WRITE
    # =========================================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('asset.management') or 'New')
        return super().create(vals_list)

    def write(self, vals):
        result = super().write(vals)
        # Sync key fields back to account.asset if linked
        sync_fields = {'amount', 'asset_name', 'capitalized_date', 'salvage_value',
                       'useful_life_years', 'depreciation_apply'}
        if sync_fields.intersection(vals.keys()):
            for rec in self:
                if rec.account_asset_id_int:
                    rec._sync_to_account_asset()
        return result

    # =========================================================================
    # ACCOUNTING ACTIONS
    # =========================================================================

    def action_confirm_asset(self):
        """Confirm the asset: create account.asset and post acquisition journal entry."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft assets can be confirmed."))
            if not rec.amount:
                raise UserError(_("Please set a Purchase Cost before confirming."))

            # 1) Create account.asset record if module is installed
            rec._create_account_asset()

            # 2) Post acquisition journal entry
            if rec.fixed_asset_account_id and rec.asset_clearing_account_id:
                rec._post_acquisition_entry()

            rec.state = 'confirmed'
            if not rec.capitalized_date:
                rec.capitalized_date = fields.Date.today()
            rec.message_post(body=_("Asset confirmed and capitalized."))
        return True

    def _create_account_asset(self):
        """Create a linked account.asset record if the module is available."""
        self.ensure_one()
        AccountAsset = self.env.get('account.asset')
        if AccountAsset is None:
            return  # account_asset module not installed

        if self.account_asset_id_int:
            return  # Already linked

        vals = {
            'name': self.asset_name or self.name,
            'original_value': self.amount,
            'salvage_value': self.salvage_value or 0.0,
            'acquisition_date': self.capitalized_date or self.invoice_date or fields.Date.today(),
            'method': 'linear' if (
                self.asset_type_id and
                self.asset_type_id.depreciation_method == 'straight_line'
            ) else 'degressive',
            'method_number': self.useful_life_years * 12 if self.useful_life_years else 60,
            'method_period': '1',
        }

        # Add account fields if available
        if self.fixed_asset_account_id:
            vals['account_asset_id'] = self.fixed_asset_account_id.id
        if self.depreciation_expense_account_id:
            vals['account_depreciation_expense_id'] = self.depreciation_expense_account_id.id
        if self.accumulated_depreciation_account_id:
            vals['account_depreciation_id'] = self.accumulated_depreciation_account_id.id
        if self.asset_journal_id:
            vals['journal_id'] = self.asset_journal_id.id

        try:
            account_asset = AccountAsset.create(vals)
            self.account_asset_id_int = account_asset.id
        except Exception as e:
            # Log warning but don't block asset confirmation
            self.message_post(
                body=_("Could not create Fixed Asset record: %s") % str(e))

    def _post_acquisition_entry(self):
        """Post the acquisition journal entry: Dr Fixed Asset / Cr Clearing Account."""
        self.ensure_one()
        if self.acquisition_move_id:
            return  # Already posted

        journal = self.asset_journal_id or self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', self.env.company.id)],
            limit=1)
        if not journal:
            raise UserError(_("Please configure an Asset Journal before confirming."))

        move_vals = {
            'journal_id': journal.id,
            'date': self.capitalized_date or self.invoice_date or fields.Date.today(),
            'ref': _('Asset Acquisition: %s') % self.name,
            'move_type': 'entry',
            'line_ids': [
                # Debit: Fixed Asset Account
                (0, 0, {
                    'name': self.asset_name or self.name,
                    'account_id': self.fixed_asset_account_id.id,
                    'debit': self.amount,
                    'credit': 0.0,
                }),
                # Credit: Asset Clearing / Payable Account
                (0, 0, {
                    'name': _('Asset Acquisition: %s') % self.name,
                    'account_id': self.asset_clearing_account_id.id,
                    'debit': 0.0,
                    'credit': self.amount,
                }),
            ],
        }
        move = self.env['account.move'].create(move_vals)
        move.action_post()
        self.acquisition_move_id = move.id

    def action_view_account_asset(self):
        """Smart button to open the linked account.asset record."""
        self.ensure_one()
        if not self.account_asset_id_int:
            raise UserError(_("No Fixed Asset record linked. Please confirm the asset first."))
        AccountAsset = self.env.get('account.asset')
        if not AccountAsset:
            raise UserError(_("The Fixed Assets module (account_asset) is not installed."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Fixed Asset'),
            'res_model': 'account.asset',
            'res_id': self.account_asset_id_int,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_journal_entries(self):
        """Smart button to view all journal entries related to this asset."""
        self.ensure_one()
        move_ids = []
        if self.acquisition_move_id:
            move_ids.append(self.acquisition_move_id.id)
        if self.disposal_move_id:
            move_ids.append(self.disposal_move_id.id)
        # Also include depreciation move entries
        dep_moves = self.depreciation_ids.filtered(
            lambda d: d.move_id).mapped('move_id').ids
        move_ids += dep_moves

        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Entries'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', move_ids)],
            'target': 'current',
        }

    def action_open_disposal_wizard(self):
        """Open the asset disposal wizard."""
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError(_("Only confirmed assets can be disposed."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Dispose Asset'),
            'res_model': 'asset.disposal.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_asset_id': self.id},
        }

    # =========================================================================
    # DEPRECIATION ENGINE
    # =========================================================================

    def generate_depreciation_entries(self):
        """Cron-triggered: Generate depreciation entries with accounting journal entries."""
        assets = self.search([
            ('state', '=', 'confirmed'),
            ('depreciation_apply', '=', True),
        ])

        for asset in assets:
            existing_count = self.env['asset.depreciation.entry'].search_count(
                [('asset_id', '=', asset.id), ('state', '=', 'posted')])
            max_entries = asset.asset_type_id.maximum_depreciation_entries

            if max_entries and existing_count >= max_entries:
                continue

            # Check if fully depreciated
            if asset.current_amount <= asset.salvage_value + 0.01:
                continue

            start_date = asset.last_depreciation_date or asset.capitalized_date or asset.invoice_date
            if not start_date:
                continue

            # Next depreciation date
            freq = asset.asset_type_id.depreciation_frequency
            delay = asset.asset_type_id.depreciation_start_delay or 1
            if freq == 'yearly':
                next_date = start_date + relativedelta(years=delay)
            elif freq == 'monthly':
                next_date = start_date + relativedelta(months=delay)
            elif freq == 'days':
                next_date = start_date + timedelta(days=delay)
            else:
                continue

            if next_date > datetime.today().date():
                continue

            depreciation_amount = asset._calculate_depreciation_amount()
            if depreciation_amount <= 0:
                continue

            # Don't depreciate below salvage value
            if (asset.current_amount - depreciation_amount) < asset.salvage_value:
                depreciation_amount = asset.current_amount - asset.salvage_value

            if depreciation_amount <= 0:
                continue

            entry = self.env['asset.depreciation.entry'].create({
                'asset_id': asset.id,
                'created_by': self.env.uid,
                'depreciation_amount': depreciation_amount,
                'entry_date': datetime.today().date(),
                'state': 'draft',
            })
            entry.action_post_depreciation()
            asset.last_depreciation_date = next_date

    def _calculate_depreciation_amount(self):
        """Calculate depreciation amount based on the asset type's method."""
        self.ensure_one()
        method = self.asset_type_id.depreciation_method
        rate = self.asset_type_id.depreciation_rate

        if method == 'fix':
            return rate

        elif method == 'percentage':
            base = self.amount if self.asset_type_id.depreciation_basis == 'real_value' \
                else self.current_amount
            return (base * rate) / 100

        elif method == 'straight_line':
            # Annual SLM: (Cost - Salvage) / Useful Life
            if self.useful_life_years <= 0:
                return 0.0
            annual = self.depreciable_amount / self.useful_life_years
            freq = self.asset_type_id.depreciation_frequency
            if freq == 'monthly':
                return annual / 12
            elif freq == 'yearly':
                return annual
            elif freq == 'days':
                return annual / 365
            return annual / 12

        elif method == 'declining_balance':
            # Declining balance: NBV × rate%
            return (self.current_amount * rate) / 100

        return 0.0

    def _sync_to_account_asset(self):
        """Sync key fields to the linked account.asset record."""
        self.ensure_one()
        if not self.account_asset_id_int:
            return
        AccountAsset = self.env.get('account.asset')
        if not AccountAsset:
            return
        try:
            account_asset = AccountAsset.browse(self.account_asset_id_int).exists()
            if not account_asset:
                return
            sync_vals = {
                'name': self.asset_name or self.name,
                'original_value': self.amount,
                'salvage_value': self.salvage_value or 0.0,
            }
            if self.capitalized_date:
                sync_vals['acquisition_date'] = self.capitalized_date
            account_asset.write(sync_vals)
        except Exception:
            pass  # Don't block write on sync failure

    # =========================================================================
    # QR CODE
    # =========================================================================

    def _get_qr_payload(self):
        self.ensure_one()
        tags = ",".join(self.tag_ids.mapped("name")) or ""
        serial = (self.serial_number or
                  (self.product_id.default_code if self.product_id else '') or
                  "").strip()
        asset_name = (self.asset_name or self.product_id.display_name
                      or self.name or "").strip()
        if serial:
            return f"BXI/Asset/{tags}/{serial}/{asset_name}"
        return f"BXI/Asset/{tags}/{asset_name}"

    def _measure_text(self, draw, text, font):
        if hasattr(draw, "textbbox"):
            left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
            return right - left, bottom - top
        return draw.textsize(text, font=font)

    def _load_font(self, size, bold=False):
        candidates = []
        if bold:
            candidates += [
                r"C:\Windows\Fonts\arialbd.ttf",
                r"C:\Windows\Fonts\calibrib.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            ]
        else:
            candidates += [
                r"C:\Windows\Fonts\arial.ttf",
                r"C:\Windows\Fonts\calibri.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            ]
        candidates += ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
        for p in candidates:
            try:
                if os.path.isabs(p) and not os.path.exists(p):
                    continue
                return ImageFont.truetype(p, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _text_width(self, draw, text, font):
        w, _ = self._measure_text(draw, text, font)
        return w

    def _wrap_text_to_width(self, draw, text, font, max_width):
        parts = text.split("/")
        lines = []
        current = ""
        for part in parts:
            candidate = f"{current}/{part}" if current else part
            if self._text_width(draw, candidate, font) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = part
        if current:
            lines.append(current)

        final_lines = []
        for ln in lines:
            if self._text_width(draw, ln, font) <= max_width:
                final_lines.append(ln)
            else:
                w_ln = max(1, self._text_width(draw, ln, font))
                est = int(len(ln) * (max_width / w_ln))
                for chunk in textwrap.wrap(ln, width=max(10, est)):
                    final_lines.append(chunk)
        return final_lines

    def action_generate_qr(self):
        self.ensure_one()
        if qrcode is None:
            raise UserError(_(
                "Python library 'qrcode' is not installed.\n"
                "Install with: pip3 install qrcode[pil] pillow"
            ))
        payload = self._get_qr_payload()
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

        draw_qr = ImageDraw.Draw(qr_img)
        w, h = qr_img.size
        center_text = "BXI"
        font_center = self._load_font(int(w * 0.13), bold=True)
        tw, th = self._measure_text(draw_qr, center_text, font_center)
        pad = int(w * 0.03)
        draw_qr.rectangle(
            [(w - tw) / 2 - pad, (h - th) / 2 - pad,
             (w + tw) / 2 + pad, (h + th) / 2 + pad], fill="white")
        draw_qr.text(((w - tw) / 2, (h - th) / 2), center_text,
                     fill=ORANGE, font=font_center)

        padding = 50
        border_margin = 8
        text_margin_lr = 30
        font_bottom = self._load_font(18, bold=False)
        tmp_canvas = Image.new("RGB", (10, 10), "white")
        tmp_draw = ImageDraw.Draw(tmp_canvas)
        max_text_width = (w + padding * 2) - (text_margin_lr * 2)
        lines = self._wrap_text_to_width(tmp_draw, payload, font_bottom, max_text_width)
        _, base_h = self._measure_text(tmp_draw, "Ag", font_bottom)
        line_height = base_h + 6
        bottom_space = max(90, (len(lines) * line_height) + 35)

        canvas_w = w + padding * 2
        canvas_h = h + padding * 2 + bottom_space
        canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
        draw = ImageDraw.Draw(canvas)
        canvas.paste(qr_img, (padding, padding))
        draw.rectangle(
            [(border_margin, border_margin),
             (canvas_w - border_margin, canvas_h - border_margin)],
            outline="black", width=2)
        y = h + padding + 18
        for ln in lines:
            lw, lh = self._measure_text(draw, ln, font_bottom)
            draw.text(((canvas_w - lw) / 2, y), ln, fill="black", font=font_bottom)
            y += line_height

        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue())
        serial = (self.serial_number or "NA").strip()
        filename = f"{self.name}_{serial}.png"
        self.write({
            "qr_payload": payload,
            "qr_image": qr_b64,
            "qr_filename": filename,
            "qr_generated_on": fields.Datetime.now(),
        })
        return {
            "type": "ir.actions.act_url",
            "url": (
                "/web/content?"
                f"model=asset.management&id={self.id}"
                "&field=qr_image"
                "&filename_field=qr_filename"
                "&download=true"
            ),
            "target": "self",
        }

    def action_open_label_layout(self):
        action = self.env['ir.actions.act_window']._for_xml_id(
            'asset_management.action_open_label_layout')
        action['context'] = {'default_asset_ids': self.ids}
        return action

    def action_view_transfers(self):
        """Smart button: open transfers for this asset."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Asset Transfers'),
            'res_model': 'asset.transfer.entry',
            'view_mode': 'list,form',
            'domain': [('asset_id', '=', self.id)],
            'context': {'default_asset_id': self.id},
        }

    def action_view_maintenance(self):
        """Smart button: open maintenance entries for this asset."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Maintenance Records'),
            'res_model': 'asset.maintenance.entry',
            'view_mode': 'list,form',
            'domain': [('asset_id', '=', self.id)],
            'context': {'default_asset_id': self.id},
        }

    def action_view_depreciation(self):
        """Smart button: open depreciation entries for this asset."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Depreciation Entries'),
            'res_model': 'asset.depreciation.entry',
            'view_mode': 'list,form',
            'domain': [('asset_id', '=', self.id)],
            'context': {'default_asset_id': self.id},
        }

    # =========================================================================
    # CONSTRAINTS
    # =========================================================================

    @api.constrains('amount', 'salvage_value')
    def _check_amounts(self):
        for rec in self:
            if rec.amount < 0:
                raise ValidationError(_("Purchase Cost cannot be negative."))
            if rec.salvage_value < 0:
                raise ValidationError(_("Salvage Value cannot be negative."))
            if rec.salvage_value > rec.amount:
                raise ValidationError(_(
                    "Salvage Value cannot exceed Purchase Cost."))


# =============================================================================
# TRANSFER ENTRY
# =============================================================================

class AssetTransferEntry(models.Model):
    _name = 'asset.transfer.entry'
    _description = 'Asset Transfer Entry'
    _order = 'assign_date desc'

    asset_id = fields.Many2one('asset.management', string="Asset Reference", required=True)
    transfer_employee_id = fields.Many2one('hr.employee', string="Assigned To", required=True)
    assign_date = fields.Date(string="Assign Date", default=fields.Date.today)
    assign_by = fields.Many2one('res.users', string="Assigned By",
                                 default=lambda self: self.env.user)
    return_date = fields.Date(string="Return Date")
    status = fields.Selection([
        ('assigned', 'Assigned'),
        ('returned', 'Returned'),
        ('under_maintenance', 'Under Maintenance'),
    ], string="Status", default='assigned')
    transfer_code = fields.Char(string="Transfer Code", copy=False, readonly=True,
                                 default=lambda self: _('New'))
    stock_qty = fields.Integer(string="Quantity", default=1)
    location = fields.Char(string="Location")
    notes = fields.Text(string="Notes")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('transfer_code', 'New') == 'New':
                vals['transfer_code'] = (
                    self.env['ir.sequence'].next_by_code('asset.transfer.entry') or 'New')
            if vals.get('asset_id') and vals.get('status') == 'assigned':
                asset = self.env['asset.management'].browse(vals['asset_id'])
                if vals.get('stock_qty', 1) <= 0:
                    raise exceptions.ValidationError(
                        _("Transfer quantity must be greater than zero."))
                if asset.model_type == 'multiple':
                    if asset.current_stock < vals.get('stock_qty', 1):
                        raise exceptions.ValidationError(
                            _("Cannot assign this asset: Insufficient stock available."))
        return super().create(vals_list)

    @api.constrains('status', 'asset_id', 'stock_qty')
    def _check_stock_availability(self):
        for rec in self:
            if rec.status == 'assigned' and rec.asset_id.model_type == 'multiple':
                others = self.search([
                    ('asset_id', '=', rec.asset_id.id),
                    ('status', '=', 'assigned'),
                    ('id', '!=', rec.id),
                ])
                total_assigned = sum(others.mapped('stock_qty'))
                available = rec.asset_id.initial_stock - total_assigned
                if available < rec.stock_qty:
                    raise exceptions.ValidationError(
                        _("Cannot assign this asset: Insufficient stock available."))


# =============================================================================
# MAINTENANCE ENTRY
# =============================================================================

class AssetMaintenanceEntry(models.Model):
    _name = 'asset.maintenance.entry'
    _description = 'Asset Maintenance Entry'
    _order = 'assign_date desc'

    asset_id = fields.Many2one('asset.management', string="Asset Reference", required=True)
    maintenance_vendor_id = fields.Many2one('asset.vendor', string="Vendor")
    assign_date = fields.Date(string="Service Start Date", default=fields.Date.today)
    assign_by = fields.Many2one('res.users', string="Requested By",
                                 default=lambda self: self.env.user)
    return_date = fields.Date(string="Completion Date")
    maintenance_status = fields.Selection([
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ], string="Status", default='pending')
    maintenance_amount = fields.Float(string="Cost")
    invoice_id = fields.Many2one('account.move', string="Invoice")
    maintenance_type = fields.Selection([
        ('preventive', 'Preventive'),
        ('corrective', 'Corrective'),
        ('emergency', 'Emergency'),
    ], string='Maintenance Type', default='preventive')
    description = fields.Text(string="Description")
    file_name = fields.Char(string='File Name')
    document = fields.Binary(string='Documents')

    @api.constrains('assign_date', 'return_date')
    def _check_dates(self):
        for rec in self:
            if rec.assign_date and rec.return_date:
                if rec.return_date < rec.assign_date:
                    raise ValidationError(
                        _("Completion Date cannot be before Service Start Date."))


# =============================================================================
# DEPRECIATION ENTRY — With Journal Entry Integration
# =============================================================================

class AssetDepreciationEntry(models.Model):
    _name = 'asset.depreciation.entry'
    _description = 'Asset Depreciation Entry'
    _order = 'entry_date desc'

    asset_id = fields.Many2one('asset.management', string="Asset Reference",
                                required=True, ondelete='cascade')
    depreciation_amount = fields.Float(string="Depreciation Amount", required=True)
    entry_date = fields.Date(string="Depreciation Date", default=fields.Date.today)
    notes = fields.Text(string="Notes")
    created_by = fields.Many2one('res.users', string="Recorded By",
                                  default=lambda self: self.env.user)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
    ], string='State', default='draft', readonly=True)
    move_id = fields.Many2one('account.move', string="Journal Entry",
                               copy=False, readonly=True)

    # ─── Depreciation Method (for reference/report) ───────────────────────────
    depreciation_method = fields.Selection(
        related='asset_id.asset_type_id.depreciation_method',
        string='Method', store=True)

    def action_post_depreciation(self):
        """Post the depreciation journal entry: Dr Expense / Cr Accumulated Depr."""
        for rec in self:
            if rec.state == 'posted':
                continue
            asset = rec.asset_id

            # If no accounting accounts configured, just mark as posted without journal entry
            if not (asset.depreciation_expense_account_id and
                    asset.accumulated_depreciation_account_id):
                rec.state = 'posted'
                rec.notes = (rec.notes or '') + \
                    '\n[Warning] Journal entry not posted: accounts not configured.'
                continue

            journal = asset.asset_journal_id or self.env['account.journal'].search(
                [('type', '=', 'general'), ('company_id', '=', self.env.company.id)],
                limit=1)
            if not journal:
                raise UserError(_(
                    "No General journal found. Please configure an Asset Journal."))

            move_vals = {
                'journal_id': journal.id,
                'date': rec.entry_date or fields.Date.today(),
                'ref': _('Depreciation: %(asset)s / %(date)s') % {
                    'asset': asset.name,
                    'date': str(rec.entry_date or fields.Date.today()),
                },
                'move_type': 'entry',
                'line_ids': [
                    # Debit: Depreciation Expense
                    (0, 0, {
                        'name': _('Depreciation: %s') % (asset.asset_name or asset.name),
                        'account_id': asset.depreciation_expense_account_id.id,
                        'debit': rec.depreciation_amount,
                        'credit': 0.0,
                        'partner_id': False,
                    }),
                    # Credit: Accumulated Depreciation
                    (0, 0, {
                        'name': _('Acc. Depreciation: %s') % (asset.asset_name or asset.name),
                        'account_id': asset.accumulated_depreciation_account_id.id,
                        'debit': 0.0,
                        'credit': rec.depreciation_amount,
                        'partner_id': False,
                    }),
                ],
            }
            move = self.env['account.move'].create(move_vals)
            move.action_post()
            rec.move_id = move.id
            rec.state = 'posted'

    def action_reset_to_draft(self):
        """Reverse the journal entry and reset to draft."""
        for rec in self:
            if rec.state != 'posted':
                continue
            if rec.move_id:
                if rec.move_id.state == 'posted':
                    rec.move_id.button_draft()
                rec.move_id.button_cancel()
                rec.move_id = False
            rec.state = 'draft'