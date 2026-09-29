# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PurchaseRequisition(models.Model):
    """Class for adding fields and functions for purchase requisition model."""
    _name = 'employee.purchase.requisition'
    _description = 'Employee Purchase Requisition'
    _inherit = "mail.thread", "mail.activity.mixin"

    name = fields.Char(string="Reference No", readonly=True)
    employee_id = fields.Many2one(comodel_name='hr.employee', string='Requested By',
                                  required=True, help='Select an employee')
    dept_id = fields.Many2one(comodel_name='hr.department', string='Department',
                              related='employee_id.department_id', store=True,
                              help='Select an department')
    user_id = fields.Many2one(comodel_name='hr.employee', string='Responsible',
                              domain=lambda self: [('share', '=', False),
                                                   ('id', '!=', self.env.uid)],
                              help='Select a user who is responsible for requisition')
    requisition_date = fields.Date(string="Requisition Date",
                                   default=lambda self: fields.Date.today(),
                                   help='Date of requisition')
    receive_date = fields.Date(string="Received Date", readonly=True,
                               help='Received date')
    requisition_deadline = fields.Date(string="Requisition Deadline",
                                       help="End date of purchase requisition")
    company_id = fields.Many2one(comodel_name='res.company', string='Company',
                                 required=True,
                                 default=lambda self: self.env.company,
                                 help='Select a company')
    requisition_order_ids = fields.One2many(comodel_name='requisition.order',
                                            inverse_name='requisition_product_id',
                                            required=True)
    confirm_id = fields.Many2one(comodel_name='res.users',
                                 string='Confirmed By',
                                 default=lambda self: self.env.uid,
                                 readonly=True,
                                 help='User who confirmed the requisition.')
    manager_id = fields.Many2one(comodel_name='res.users',
                                 string='Department Manager', readonly=True,
                                 help='Select a department manager')
    requisition_head_id = fields.Many2one(comodel_name='res.users',
                                          string='Approved By', readonly=True,
                                          help='User who approved the requisition.')
    rejected_user_id = fields.Many2one(comodel_name='hr.employee',
                                       string='Rejected By', readonly=True,
                                       help='User who rejected the requisition')
    confirmed_date = fields.Date(string='Confirmed Date', readonly=True,
                                 help='Date of requisition confirmation')
    department_approval_date = fields.Date(string='Department Approval Date',
                                           readonly=True,
                                           help='Department approval date')
    approval_date = fields.Date(string='Approved Date', readonly=True,
                                help='Requisition approval date')
    reject_date = fields.Date(string='Rejection Date', readonly=True,
                              help='Requisition rejected date')
    source_location_id = fields.Many2one(
        comodel_name='stock.location',
        string='Source Location',
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help='Source location of requisition.',
    )
    destination_location_id = fields.Many2one(
        comodel_name='stock.location',
        string="Destination Location",
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help='Destination location of requisition.',
    )
    delivery_type_id = fields.Many2one(
        comodel_name='stock.picking.type',
        string='Delivery To',
        domain="[('company_id', '=', company_id), ('code', '=', 'incoming')]",
        help='Type of delivery.',
    )
    internal_picking_id = fields.Many2one(
        comodel_name='stock.picking.type',
        string="Internal Picking",
        domain="[('company_id', '=', company_id), ('code', '=', 'internal')]",
        help='Internal picking type.',
    )
    requisition_description = fields.Text(string="Reason For Requisition")
    purchase_count = fields.Integer(string='Purchase Count',
                                    help='Purchase count',
                                    compute='_compute_purchase_count')
    internal_transfer_count = fields.Integer(string='Internal Transfer count',
                                             help='Internal transfer count',
                                             compute='_compute_internal_transfer_count')
    state = fields.Selection([('new', 'New'), 
                            # ('waiting_department_approval','Waiting HR Approval'),
                            ('waiting_head_approval','Waiting Finance Approval'),
                            ('approved', 'Approved'),
                            ('purchase_order_created','Purchase Order Created'),
                            ('received', 'Received'),
                            ('cancelled', 'Cancelled')], default='new', copy=False, tracking=True)

    req_type = fields.Selection([('internal', 'Internal'),
                                ('customer', 'Customer')], default='internal',
                             copy=False, tracking=True)
    customer_id = fields.Many2one(comodel_name='res.partner',
                                 string='Customer', readonly=True,
                                 domain="[('customer_type', 'in', ('customer', 'customer_and_vendor'))]",
                                 help='Select a Customer')

    @api.model
    def _get_or_create_warehouse(self, company):
        """Find or automatically create a warehouse for the given company to ensure picking types & stock locations exist."""
        if not company:
            return False
        warehouse = self.env['stock.warehouse'].sudo().search([('company_id', '=', company.id)], limit=1)
        if not warehouse:
            clean_name = ''.join(c for c in company.name if c.isalnum()).upper()
            code_base = clean_name[:4] if clean_name else 'WH'
            code = code_base
            idx = 1
            while self.env['stock.warehouse'].sudo().search([('code', '=', code)], limit=1):
                code = f"{code_base[:3]}{idx}"
                idx += 1
            warehouse = self.env['stock.warehouse'].sudo().with_company(company).create({
                'name': company.name,
                'code': code,
                'company_id': company.id,
                'partner_id': company.partner_id.id,
            })
        return warehouse

    @api.onchange('company_id', 'employee_id')
    def _onchange_company_id(self):
        """Update picking details and locations to strictly match the selected company."""
        for rec in self:
            if not rec.company_id:
                rec.source_location_id = False
                rec.destination_location_id = False
                rec.delivery_type_id = False
                rec.internal_picking_id = False
                continue
            warehouse = rec._get_or_create_warehouse(rec.company_id)
            dept_loc = rec.employee_id.sudo().department_id.department_location_id if rec.employee_id else False
            rec.source_location_id = dept_loc.id if (dept_loc and (not dept_loc.company_id or dept_loc.company_id == rec.company_id)) else (
                warehouse.lot_stock_id.id if warehouse else False
            )
            emp_loc = rec.employee_id.sudo().employee_location_id if rec.employee_id else False
            rec.destination_location_id = emp_loc.id if (emp_loc and (not emp_loc.company_id or emp_loc.company_id == rec.company_id)) else (
                warehouse.lot_stock_id.id if warehouse else False
            )
            rec.delivery_type_id = warehouse.in_type_id.id if (warehouse and warehouse.in_type_id) else False
            rec.internal_picking_id = warehouse.int_type_id.id if (warehouse and warehouse.int_type_id) else False

    @api.model_create_multi
    def create(self, vals_list):
        """Generate purchase requisition sequence and set respective company picking details"""
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                comp_id = vals.get('company_id') or self.env.company.id
                vals['name'] = self.env['ir.sequence'].with_company(comp_id).next_by_code(
                    'employee.purchase.requisition'
                ) or 'New'

            comp_id = vals.get('company_id') or self.env.company.id
            if comp_id:
                company = self.env['res.company'].sudo().browse(comp_id)
                warehouse = self._get_or_create_warehouse(company)
                if warehouse:
                    if not vals.get('delivery_type_id') and warehouse.in_type_id:
                        vals['delivery_type_id'] = warehouse.in_type_id.id
                    if not vals.get('internal_picking_id') and warehouse.int_type_id:
                        vals['internal_picking_id'] = warehouse.int_type_id.id
                    if not vals.get('source_location_id') and warehouse.lot_stock_id:
                        vals['source_location_id'] = warehouse.lot_stock_id.id
                    if not vals.get('destination_location_id') and warehouse.lot_stock_id:
                        vals['destination_location_id'] = warehouse.lot_stock_id.id

        records = super().create(vals_list)

        template = self.env.ref(
            'employee_purchase_requisition.email_template_requisition_submit',
            raise_if_not_found=False
        )

        for rec in records:
            if template:
                template.send_mail(rec.id, force_send=True)

        return records

    def action_confirm_requisition(self):
        """Function to confirm purchase requisition with respective company details"""
        for rec in self:
            warehouse = rec._get_or_create_warehouse(rec.company_id)

            dept_loc = rec.employee_id.sudo().department_id.department_location_id
            rec.source_location_id = dept_loc.id if (dept_loc and (not dept_loc.company_id or dept_loc.company_id == rec.company_id)) else (
                warehouse.lot_stock_id.id if warehouse else False
            )

            emp_loc = rec.employee_id.sudo().employee_location_id
            rec.destination_location_id = emp_loc.id if (emp_loc and (not emp_loc.company_id or emp_loc.company_id == rec.company_id)) else (
                warehouse.lot_stock_id.id if warehouse else False
            )

            rec.delivery_type_id = warehouse.in_type_id.id if (warehouse and warehouse.in_type_id) else False
            rec.internal_picking_id = warehouse.int_type_id.id if (warehouse and warehouse.int_type_id) else False
            rec.write({'state': 'waiting_head_approval'})
            rec.confirm_id = rec.env.uid
            rec.confirmed_date = fields.Date.today()

    def action_department_approval(self):
        """Approval from department"""
        self.write({'state': 'waiting_head_approval'})
        self.manager_id = self.env.uid
        self.department_approval_date = fields.Date.today()

    def action_department_cancel(self):
        """Cancellation from department """
        self.write({'state': 'cancelled'})
        self.rejected_user_id = self.env.uid
        self.reject_date = fields.Date.today()

    def action_head_approval(self):
        """Approval from department head"""
        self.write({'state': 'approved'})
        self.requisition_head_id = self.env.uid
        self.approval_date = fields.Date.today()
        template = self.env.ref(
            'employee_purchase_requisition.email_template_requisition_approved',
            raise_if_not_found=False
        )

        for rec in self:
            if template:
                template.send_mail(rec.id, force_send=True)

    def action_head_cancel(self):
        """Cancellation from department head"""
        self.write({'state': 'cancelled'})
        self.rejected_user_id = self.env.uid
        self.reject_date = fields.Date.today()

    def action_create_purchase_order(self):
        """Create purchase order and internal transfer with respective company details following standard purchasing flow."""
        created_pos = self.env['purchase.order']
        created_pickings = self.env['stock.picking']

        for req in self:
            warehouse = req._get_or_create_warehouse(req.company_id)

            # Ensure picking details strictly match the requisition's company
            vals_to_fix = {}
            if not req.delivery_type_id or req.delivery_type_id.company_id != req.company_id:
                vals_to_fix['delivery_type_id'] = warehouse.in_type_id.id if (warehouse and warehouse.in_type_id) else False
            if not req.internal_picking_id or req.internal_picking_id.company_id != req.company_id:
                vals_to_fix['internal_picking_id'] = warehouse.int_type_id.id if (warehouse and warehouse.int_type_id) else False
            if not req.source_location_id or (req.source_location_id.company_id and req.source_location_id.company_id != req.company_id):
                vals_to_fix['source_location_id'] = warehouse.lot_stock_id.id if (warehouse and warehouse.lot_stock_id) else False
            if not req.destination_location_id or (req.destination_location_id.company_id and req.destination_location_id.company_id != req.company_id):
                vals_to_fix['destination_location_id'] = warehouse.lot_stock_id.id if (warehouse and warehouse.lot_stock_id) else False
            if vals_to_fix:
                req.write(vals_to_fix)

            po_lines = req.requisition_order_ids.filtered(lambda l: l.requisition_type == 'purchase_order')
            it_lines = req.requisition_order_ids.filtered(lambda l: l.requisition_type == 'internal_transfer')

            # Validate vendor for PO lines
            for rec in po_lines:
                if not rec.partner_id:
                    raise ValidationError('Please select a vendor for all Purchase Order lines.')

            # 1. Standard Flow: Group purchase order lines by vendor (1 PO per vendor)
            if po_lines:
                vendor_grouped = {}
                for rec in po_lines:
                    vendor_grouped.setdefault(rec.partner_id, []).append(rec)

                picking_type = req.delivery_type_id or (warehouse.in_type_id if warehouse else False)

                for vendor, lines in vendor_grouped.items():
                    order_lines = []
                    for line in lines:
                        order_lines.append((0, 0, {
                            'product_id': line.product_id.id,
                            'name': line.description or line.product_id.display_name,
                            'product_qty': line.quantity,
                            'product_uom_id': line.product_id.uom_id.id,
                            'company_id': req.company_id.id,
                        }))

                    po = req.env['purchase.order'].sudo().with_company(req.company_id).with_context(company_id=req.company_id.id).create({
                        'partner_id': vendor.id,
                        'company_id': req.company_id.id,
                        'picking_type_id': picking_type.id if picking_type else False,
                        'origin': req.name,
                        'requisition_order': req.name,
                        'order_line': order_lines,
                    })
                    created_pos |= po

            # 2. Internal Transfers: Group all internal transfer lines into a single picking
            if it_lines:
                picking_type = req.internal_picking_id or (warehouse.int_type_id if warehouse else False)
                src_loc = req.source_location_id or (warehouse.lot_stock_id if warehouse else False)
                dest_loc = req.destination_location_id or (warehouse.lot_stock_id if warehouse else False)
                move_lines = []
                for rec in it_lines:
                    move_lines.append((0, 0, {
                        'name': rec.description or rec.product_id.display_name,
                        'product_id': rec.product_id.id,
                        'product_uom': rec.product_id.uom_id.id,
                        'product_uom_qty': rec.quantity,
                        'location_id': src_loc.id if src_loc else False,
                        'location_dest_id': dest_loc.id if dest_loc else False,
                        'company_id': req.company_id.id,
                    }))

                picking = req.env['stock.picking'].sudo().with_company(req.company_id).create({
                    'location_id': src_loc.id if src_loc else False,
                    'location_dest_id': dest_loc.id if dest_loc else False,
                    'picking_type_id': picking_type.id if picking_type else False,
                    'company_id': req.company_id.id,
                    'origin': req.name,
                    'requisition_order': req.name,
                    'move_ids_without_package': move_lines,
                })
                created_pickings |= picking

            req.write({'state': 'purchase_order_created'})

        # Return action to immediately open created Purchase Order(s)
        if len(created_pos) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Purchase Order',
                'view_mode': 'form',
                'res_model': 'purchase.order',
                'res_id': created_pos.id,
                'target': 'current',
            }
        elif len(created_pos) > 1:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Purchase Orders',
                'view_mode': 'list,form',
                'res_model': 'purchase.order',
                'domain': [('id', 'in', created_pos.ids)],
                'target': 'current',
            }
        elif len(created_pickings) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Internal Transfer',
                'view_mode': 'form',
                'res_model': 'stock.picking',
                'res_id': created_pickings.id,
                'target': 'current',
            }
        elif len(created_pickings) > 1:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Internal Transfers',
                'view_mode': 'list,form',
                'res_model': 'stock.picking',
                'domain': [('id', 'in', created_pickings.ids)],
                'target': 'current',
            }

    def _compute_internal_transfer_count(self):
        """Function to compute the transfer count"""
        for rec in self:
            rec.internal_transfer_count = rec.env['stock.picking'].sudo().search_count([
                '|', ('requisition_order', '=', rec.name), ('origin', '=', rec.name)
            ]) if rec.name else 0

    def _compute_purchase_count(self):
        """Function to compute the purchase count"""
        for rec in self:
            rec.purchase_count = rec.env['purchase.order'].sudo().search_count([
                '|', ('requisition_order', '=', rec.name), ('origin', '=', rec.name)
            ]) if rec.name else 0

    def action_receive(self):
        """Received purchase requisition"""
        self.write({'state': 'received'})
        self.receive_date = fields.Date.today()

    def get_purchase_order(self):
        """Purchase order smart button view"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Purchase Order',
            'view_mode': 'list,form',
            'res_model': 'purchase.order',
            'domain': ['|', ('requisition_order', '=', self.name), ('origin', '=', self.name)],
        }

    def get_internal_transfer(self):
        """Internal transfer smart tab view"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Internal Transfers',
            'view_mode': 'list,form',
            'res_model': 'stock.picking',
            'domain': [('requisition_order', '=', self.name)],
        }

    def action_print_report(self):
        """Print purchase requisition report"""
        data = {
            'employee': self.employee_id.name,
            'records': self.read(),
            'order_ids': self.requisition_order_ids.read(),
        }
        return (self.env.ref(
            'employee_purchase_requisition.'
            'action_report_purchase_requisition').report_action(
            self, data=data))
