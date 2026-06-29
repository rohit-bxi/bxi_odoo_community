from odoo import models, fields, api, _, exceptions
from dateutil.relativedelta import relativedelta
from datetime import datetime, timedelta
# -*- coding: utf-8 -*-
import base64
import io
import os
import textwrap
from PIL import Image, ImageDraw, ImageFont
from odoo.exceptions import UserError

ORANGE = (255, 140, 0)  # orange

try:
    import qrcode
except ImportError:
    qrcode = None


class Asset(models.Model):
    _name = 'asset.management'
    _description = 'Asset Management'

    # Basic Asset Information
    name = fields.Char(string="Asset Reference", required=True, copy=False, readonly=True,
                       default=lambda self: _('New'))
    barcode = fields.Char(string="Barcode", copy=False, help="Barcode for asset identification and scanning")
    product_id = fields.Many2one('product.product', string="Associated Product", help="Select the product used in this asset from available options")
    asset_type_id = fields.Many2one('asset.type', string="Asset Type", help="Classification of the asset (e.g., Equipment, Vehicle, Building)")
    # Model Type and Stock Management
    model_type = fields.Selection([
        ('single', 'Single Asset'),
        ('multiple', 'Multiple Assets')
    ], string="Model Type", default='single', required=True, 
       help="Single: Unique asset with specific tracking. Multiple: Assets with stock management")
    
    initial_stock = fields.Integer(string="Initial Stock", default=1,
                                  help="Initial quantity of this asset")
    current_stock = fields.Integer(string="Current Stock", compute='_compute_current_stock', store=True,
                                  help="Current available quantity of this asset")
    active_transfers = fields.Integer(string="Active Transfers", compute='_compute_active_transfers', store=True,
                                     help="Number of assets currently assigned to users")
    
    # Depreciation Settings
    depreciation_apply = fields.Boolean(string="Enable Depreciation", help="Check to apply depreciation calculations for this asset")
    
    # Vendor and Purchase Information
    expired_warranty_date = fields.Date(string="Asset Expiry Date")
    warranty_date = fields.Date(string="Warranty Expiry Date")
    vendor_id = fields.Many2one('asset.vendor', string="Associated Vendor", help="Select the vendor or supplier of this asset")
    invoice_date = fields.Date(string="Invoice Date", help="Date when the asset was purchased or acquired")
    amount = fields.Float(string="Purchase Price", help="Initial cost of acquiring the asset")
    
    # Computed Financial Fields
    current_amount = fields.Float(string="Current Book Value", compute="_compute_current_amount", help="Current value of the asset after depreciation (Read-only)")
    total_depreciation_amount = fields.Float(string="Accumulated Depreciation",
                                             compute='_compute_total_depreciation_amount', store=True, help="Total depreciation applied to the asset to date (Read-only)")
    total_maintenance_amount = fields.Float(string="Total Maintenance Cost",
                                            compute='_compute_total_maintenance_amount', store=True, help="Sum of all maintenance expenses for this asset (Read-only)")
    # Asset Status 
    status = fields.Selection([
        ('assign', 'Assign'),
        ('return', 'Return'),
        ('on_hold', 'On Hold'),
        ('in_warehouse', 'In Warehouse'),
        ('repair', 'Repair'),
        ('destroyed', 'Destroyed')
    ], string="Status", default="assign")

    # Related Documents and Entries
    document_ids = fields.Many2many('ir.attachment', string="Asset Documentation", help="Upload multiple documents related to the asset (e.g., Warranty,Invoice)")
    tag_ids = fields.Many2many('asset.tag', string='Tags', help="Categorize assets with tags for easier filtering and organization")
    transfer_ids = fields.One2many('asset.transfer.entry', 'asset_id', string="Transfer Entries")
    maintenance_ids = fields.One2many('asset.maintenance.entry', 'asset_id', string="Maintenance Entries")
    depreciation_ids = fields.One2many('asset.depreciation.entry', 'asset_id', string="Depreciation Entries")
    
    # Additional Information
    last_depreciation_date = fields.Date(string="Last Depreciation Date", help="Last Depreciation Entry Date", readonly=True)
    transfer_count = fields.Integer(string='Asset Transfer History',
                                    compute='_compute_all_count', store=True)
    maintenance_count = fields.Integer(string='Maintenance Records',
                                       compute='_compute_all_count', store=True)
    depreciation_count = fields.Integer(string='Depreciation Count',
                                        compute='_compute_all_count', store=True)
    invoice_id = fields.Many2one('account.move', string="Associated Invoice")
    months_left = fields.Integer(string='Months Left',)
    assigned_user = fields.Char(string="Assigned User", compute='_compute_assigned_user',
                                store=True)
    assign_by = fields.Char(string="Assigned By", compute='_compute_assigned_user',
                                store=True)
    remaining_warranty = fields.Char(string="Remaining Warranty",
                                     compute="_compute_months_left", store=True)
    warranty_status = fields.Char(string='Warranty Status')
    asset_configuration = fields.Text(string='Asset Configuration(If Any)')

    qr_payload = fields.Char(string="QR Payload", copy=False, readonly=True)
    qr_image = fields.Binary(string="QR Code", copy=False, readonly=True, attachment=True)
    qr_filename = fields.Char(string="QR Filename", copy=False, readonly=True)
    qr_generated_on = fields.Datetime(string="QR Generated On", copy=False, readonly=True)

    def _get_qr_payload(self):
        self.ensure_one()

        if not self.product_id:
            raise UserError(_("Please set Associated Product before generating QR."))

        tags = ",".join(self.tag_ids.mapped("name")) or ""

        # Serial number = Internal Reference from product
        serial = (self.product_id.default_code or "").strip()
        if not serial:
            asset_name = (self.product_id.display_name or self.name or "").strip()
            return f"BXI/Tech/{tags}/{asset_name}"

        asset_name = (self.product_id.display_name or self.name or "").strip()
        return f"BXI/Tech/{tags}/{serial}/{asset_name}"

    def _measure_text(self, draw, text, font):
        """
        Pillow version safe text measurement.
        New Pillow: draw.textbbox()
        Old Pillow: draw.textsize()
        """
        if hasattr(draw, "textbbox"):
            left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
            return right - left, bottom - top
        return draw.textsize(text, font=font)

    def _load_font(self, size, bold=False):
        """
        Cross-platform font loader (Windows local + Ubuntu production).
        Tries OS font paths first, then DejaVu names, then falls back.
        """
        candidates = []

        # Windows fonts
        if bold:
            candidates += [
                r"C:\Windows\Fonts\arialbd.ttf",
                r"C:\Windows\Fonts\calibrib.ttf",
                r"C:\Windows\Fonts\verdana.ttf",
            ]
        else:
            candidates += [
                r"C:\Windows\Fonts\arial.ttf",
                r"C:\Windows\Fonts\calibri.ttf",
                r"C:\Windows\Fonts\verdana.ttf",
            ]

        # Ubuntu/Linux fonts
        if bold:
            candidates += [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            ]
        else:
            candidates += [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            ]

        # Pillow bundled names
        candidates += [
            "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        ]

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
        """
        Wrap long payload to multiple lines so it doesn't cut.
        Wrap by '/' boundaries first, then character wrap if needed.
        """
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

        # Still too long? force char wrap
        final_lines = []
        for ln in lines:
            if self._text_width(draw, ln, font) <= max_width:
                final_lines.append(ln)
            else:
                # Estimate wrap width conservatively
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

        # 1) Generate QR (extra quiet zone so it doesn't look cut)
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

        # 2) Put "BXI" in center (orange)
        draw_qr = ImageDraw.Draw(qr_img)
        w, h = qr_img.size

        center_text = "BXI"
        font_center = self._load_font(int(w * 0.13), bold=True)

        tw, th = self._measure_text(draw_qr, center_text, font_center)

        pad = int(w * 0.03)
        x0 = (w - tw) / 2 - pad
        y0 = (h - th) / 2 - pad
        x1 = (w + tw) / 2 + pad
        y1 = (h + th) / 2 + pad
        draw_qr.rectangle([(x0, y0), (x1, y1)], fill="white")

        draw_qr.text(((w - tw) / 2, (h - th) / 2), center_text, fill=ORANGE, font=font_center)

        # 3) Build canvas with padding + border
        padding = 50
        border_margin = 8
        text_margin_lr = 30  # safer wrap (prevents edge cutting)

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
            [(border_margin, border_margin), (canvas_w - border_margin, canvas_h - border_margin)],
            outline="black",
            width=2,
        )

        # 4) Draw wrapped bottom text
        y = h + padding + 18
        for ln in lines:
            lw, lh = self._measure_text(draw, ln, font_bottom)
            draw.text(((canvas_w - lw) / 2, y), ln, fill="black", font=font_bottom)
            y += line_height

        # 5) Save to binary and write to record
        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue())

        serial = (self.product_id.default_code or "NA").strip()
        filename = f"{(self.name or 'ASSET')}_{serial}.png"

        self.write({
            "qr_payload": payload,
            "qr_image": qr_b64,
            "qr_filename": filename,
            "qr_generated_on": fields.Datetime.now(),
        })

        # 6) Auto-download
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


    @api.depends('transfer_ids', 'transfer_ids.status', 'transfer_ids.stock_qty')
    def _compute_active_transfers(self):
        for record in self:
            # Count transfers that are in 'assigned' status and sum their quantities
            assigned_transfers = record.transfer_ids.filtered(lambda t: t.status == 'assigned')
            record.active_transfers = sum(assigned_transfers.mapped('stock_qty'))

    @api.depends('initial_stock', 'active_transfers')
    def _compute_current_stock(self):
        for record in self:
            record.current_stock = record.initial_stock - record.active_transfers

    # Compute methods
    @api.depends('expired_warranty_date')
    def _compute_months_left(self):
        today = fields.Date.today()
        for record in self:
            if record.expired_warranty_date:
                if record.expired_warranty_date < today:
                    record.remaining_warranty = 'Expired'
                    record.warranty_status = 'expired'

                elif record.expired_warranty_date == today:
                    record.remaining_warranty = 'Today'
                    record.warranty_status = 'danger'

                else:
                    rd = relativedelta(record.expired_warranty_date, today)
                    total_months = rd.years * 12 + rd.months + (
                                rd.days / 30)  # Approximate

                    if total_months > 6:
                        record.warranty_status = 'success'
                    elif 3 <= total_months <= 6:
                        record.warranty_status = 'warning'
                    else:
                        record.warranty_status = 'danger'
                    years = rd.years
                    months = rd.months
                    days = rd.days

                    parts = []
                    if years > 0:
                        parts = [f"{years} year{'s' if years > 1 else ''}"]
                    elif months > 0:
                        parts = [f"{months} month{'s' if months > 1 else ''}"]
                    elif days > 0:
                        parts = [f"{days} day{'s' if days > 1 else ''}"]
                    
                       
                    print("parts : ", parts)
                    record.remaining_warranty = ', '.join(parts)

            else:
                record.remaining_warranty = 'No warranty'
                record.warranty_status = 'expired'

    @api.depends('transfer_ids')
    def _compute_assigned_user(self):
        for record in self:
            # Check if there are any transfer entries
            if record.transfer_ids:
                # Retrieve the most recent transfer entry based on 'assign_date'
                last_transfer = record.transfer_ids[-1]
                if last_transfer:
                    # Get the user who assigned the asset in the last transfer
                    record.assigned_user = last_transfer.transfer_employee_id.name
                    record.assign_by = last_transfer.assign_by.id
                else:
                    record.assigned_user = ''
                    record.assign_by = ''
            else:
                # Handle the case where there are no transfer entries
                record.assigned_user = ''
                record.assign_by = ''

    @api.depends('transfer_ids', 'maintenance_ids', 'depreciation_ids')
    def _compute_all_count(self):
        for record in self:
            record.transfer_count = len(record.transfer_ids)
            record.maintenance_count = len(record.maintenance_ids)
            record.depreciation_count = len(record.depreciation_ids)

    @api.depends('amount',)
    def _compute_current_amount(self):
        for record in self:
            record.current_amount = record.amount - record.total_depreciation_amount

    @api.depends('depreciation_ids.depreciation_amount')
    def _compute_total_depreciation_amount(self):
        for record in self:
            record.total_depreciation_amount = sum(record.depreciation_ids.mapped('depreciation_amount'))

    @api.depends('maintenance_ids.maintenance_amount')
    def _compute_total_maintenance_amount(self):
        for record in self:
            record.total_maintenance_amount = sum(record.maintenance_ids.mapped('maintenance_amount'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('asset.management') or 'New'
        return super(Asset, self).create(vals_list)

    def generate_depreciation_entries(self):
        """Generate depreciation entries with value subtraction."""
        assets = self.search(
            [('status', '!=', 'destroyed'), ('depreciation_apply', '=', True)])

        for asset in assets:
            # Check if the maximum number of depreciation entries has been reached
            existing_entries_count = self.env['asset.depreciation.entry'].search_count(
                [('asset_id', '=', asset.id),('create_uid', '=', 1)])
            max_entries = asset.asset_type_id.maximum_depreciation_entries

            if max_entries and existing_entries_count >= max_entries:
                continue  # Skip this asset if the maximum number of entries has been reached

            # Determine the starting date for depreciation
            start_date = asset.last_depreciation_date if asset.last_depreciation_date else asset.invoice_date
            if not start_date:
                continue  # Skip if no valid starting date

            # Calculate next depreciation date
            if asset.asset_type_id.depreciation_frequency == 'yearly':
                next_depreciation_date = start_date + relativedelta(
                    years=asset.asset_type_id.depreciation_start_delay)
            elif asset.asset_type_id.depreciation_frequency == 'monthly':
                next_depreciation_date = start_date + relativedelta(
                    months=asset.asset_type_id.depreciation_start_delay)
            elif asset.asset_type_id.depreciation_frequency == 'days':
                next_depreciation_date = start_date + timedelta(
                    days=asset.asset_type_id.depreciation_start_delay)
            else:
                continue  # Invalid depreciation type

            # Check if depreciation needs to be applied today
            if next_depreciation_date > datetime.today().date():
                continue  # Skip if next depreciation date is in the future

            # Determine the depreciation amount and subtract it from the value
            if asset.asset_type_id.depreciation_method == 'fix':
                depreciation_amount = asset.asset_type_id.depreciation_rate
            elif asset.asset_type_id.depreciation_method == 'percentage':
                base_amount = asset.amount if asset.asset_type_id.depreciation_basis == 'real_value' else asset.current_amount
                depreciation_amount = (
                                                  base_amount * asset.asset_type_id.depreciation_rate) / 100
            else:
                continue  # Invalid depreciation value type

            # Subtract the depreciation amount from the asset's value
            if asset.asset_type_id.depreciation_basis == 'real_value':
                asset.amount -= depreciation_amount
            else:
                asset.total_depreciation_amount -= depreciation_amount

            # Update the last depreciation date and create an entry in the depreciation model
            asset.last_depreciation_date = next_depreciation_date

            # Create a depreciation entry in the 'asset.depreciation' model
            self.env['asset.depreciation.entry'].create({
                'asset_id': asset.id,
                'created_by': self.env.uid,
                'depreciation_amount': depreciation_amount,
                'entry_date': datetime.today().date(),
            })

            print(
                f"Depreciation Entry Created for {asset.name}: {depreciation_amount} deducted on {next_depreciation_date}"
            )

    def action_open_label_layout(self):
        """Open the label layout wizard for printing asset labels"""
        action = self.env['ir.actions.act_window']._for_xml_id('asset_management.action_open_label_layout')
        action['context'] = {'default_asset_ids': self.ids}
        return action


class AssetTag(models.Model):
    _name = 'asset.tag'
    _description = 'Asset Tag'

    name = fields.Char(string='Name', required=True)
    color = fields.Integer(string='Color Index')
    
    _sql_constraints = [
        ('name_uniq', 'unique (name)', "Tag name already exists!"),
    ]


class AssetTransferEntry(models.Model):
    _name = 'asset.transfer.entry'
    _description = 'Asset Transfer Entry'

    # Fields for tracking asset transfers
    asset_id = fields.Many2one('asset.management', string="Asset Reference", help="Choose the asset for which the transfer is being recorded")
    transfer_employee_id = fields.Many2one('hr.employee', string="Assigned To", help="Employee who is receiving or has received the asset")
    assign_date = fields.Date(string="Assign Date", help="Date when the asset was assigned to the employee")
    assign_by = fields.Many2one('res.users', string="Assign By", default=lambda self: self.env.user, help="Person responsible for assigning the asset")
    return_date = fields.Date(string="Return Date", help="Date when the asset was returned by the employee")
    status = fields.Selection([
        ('assigned', 'Assigned'),
        ('returned', 'Returned'),
        ('under_maintenance', 'Under Maintenance')
    ], string="Status", help="Current status of the asset transfer")
    transfer_code = fields.Char(string="Transfer Code", copy=False, readonly=True, 
                               default=lambda self: _('New'), help="Unique identifier for this transfer")
    stock_qty = fields.Integer(string="Quantity", default=1, 
                              help="Quantity of assets being transferred (for multiple assets)")
    location = fields.Char(string="Location")
    
    @api.model_create_multi
    def create(self, vals_list):
        """Override create to generate transfer code and check stock availability"""
        for vals in vals_list:
            if vals.get('transfer_code', 'New') == 'New':
                vals['transfer_code'] = self.env['ir.sequence'].next_by_code('asset.transfer.entry') or 'New'
            
            if vals.get('asset_id') and vals.get('status') == 'assigned':
                asset = self.env['asset.management'].browse(vals['asset_id'])
                # Check if stock quantity is valid
                if vals.get('stock_qty', 1) <= 0:
                    raise exceptions.ValidationError(_("Transfer quantity must be greater than zero."))
                    
                if asset.model_type == 'multiple':
                    if asset.current_stock < vals.get('stock_qty', 1):
                        raise exceptions.ValidationError(_("Cannot assign this asset: Insufficient stock available."))
        return super(AssetTransferEntry, self).create(vals_list)

    @api.constrains('status', 'asset_id', 'stock_qty')
    def _check_stock_availability(self):
        """Ensure stock is available when assigning assets"""
        for record in self:
            if record.status == 'assigned' and record.asset_id.model_type == 'multiple':
                # Get current stock after excluding this record (important for updates)
                other_transfers = self.search([
                    ('asset_id', '=', record.asset_id.id),
                    ('status', '=', 'assigned'),
                    ('id', '!=', record.id)
                ])
                total_assigned = sum(other_transfers.mapped('stock_qty'))
                available = record.asset_id.initial_stock - total_assigned
                if available < record.stock_qty:
                    raise exceptions.ValidationError(_("Cannot assign this asset: Insufficient stock available."))

class AssetMaintenanceEntry(models.Model):
    _name = 'asset.maintenance.entry'
    _description = 'Asset Maintenance Entry'

    # Fields for tracking asset maintenance
    asset_id = fields.Many2one('asset.management', string="Asset Reference", help="Choose the asset for undergoing maintenance or repair is being recorded")
    maintenance_vendor_id = fields.Many2one('asset.vendor', string="Select Vendor", help="Vendor or technician performing the maintenance or repair")
    assign_date = fields.Date(string="Service Start Date", help="Date when the asset was sent for maintenance or repair")
    assign_by = fields.Many2one('res.users', string="Requested By", default=lambda self: self.env.user, help="Person who initiated the maintenance or repair request")
    return_date = fields.Date(string="Completion Date", help="Date when the maintenance or repair was completed")
    maintenance_status = fields.Selection([
        ('in_progress', 'In Progress'),
        ('pending', 'Pending'),
        ('completed', 'Completed')
    ], string="Status", help="Current status of the maintenance or repair process")
    maintenance_amount = fields.Float(string="Amount")
    invoice_id = fields.Many2one('account.move', string="Invoice")
    file_name = fields.Char(string='File Name')
    document = fields.Binary(string='Documents', required=True)


class AssetDepreciationEntry(models.Model):
    _name = 'asset.depreciation.entry'
    _description = 'Asset Depreciation Entry'

    # Fields for tracking asset depreciation
    asset_id = fields.Many2one('asset.management', string="Asset Reference", help="Choose the asset for which depreciation is being recorded")
    depreciation_amount = fields.Float(string="Amount", help="The monetary value of depreciation applied in this entry")
    entry_date = fields.Date(string="Depreciation Date", help="Date when this depreciation entry was recorded")
    notes = fields.Text(string="Comments", help="Additional information or remarks about this depreciation entry")
    created_by = fields.Many2one('res.users', string="Recorded By", default=lambda self: self.env.user, help="Person who created this depreciation entry")


class AssetType(models.Model):
    _name = 'asset.type'
    _description = 'Asset Type'

    # Fields for defining asset types and their depreciation rules
    name = fields.Char(string='Name', required=True)
    color = fields.Integer(string='Color Index', help="Color index for this asset type")
    depreciation_frequency = fields.Selection([
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
        ('days', 'Days')
    ], string='Depreciation Frequency', required=True, help="How often depreciation is calculated (Yearly, Monthly, or Daily)")

    depreciation_method = fields.Selection([
        ('fix', 'Fix'),
        ('percentage', 'Percentage')
    ], string='Depreciation Value Type', required=True, help="Whether depreciation is calculated as a percentage or fixed amount")

    depreciation_rate = fields.Float(string='Depreciation Rate', help="The percentage or fixed amount used to calculate depreciation")
    depreciation_start_delay = fields.Integer(string='Depreciation Start Delay', help="Time duration before depreciation begins after asset acquisition")
    depreciation_basis = fields.Selection([
        ('real_value', 'Purchase Price'),
        ('depreciation_value', 'Book Price')
    ], string='Depreciation Basis', required=True, help="Whether depreciation is applied to the adjusted value (after previous depreciation) or the original value")
    maximum_depreciation_entries = fields.Integer(string="Maximum Depreciation Entries", help="The maximum number of depreciation entries allowed for this asset type")