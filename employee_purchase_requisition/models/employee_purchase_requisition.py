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
                                 string='Manager Approved By', readonly=True,
                                 help='Manager who approved the requisition.')
    manager_approval_date = fields.Date(string='Manager Approval Date',
                                        readonly=True,
                                        help='Date of manager approval')
    ra_id = fields.Many2one(comodel_name='res.users',
                            string='Revenue Assurance Approved By', readonly=True,
                            help='Revenue Assurance user who approved the requisition.')
    ra_approval_date = fields.Date(string='Revenue Assurance Approval Date',
                                   readonly=True,
                                   help='Date of Revenue Assurance approval')
    finance_id = fields.Many2one(comodel_name='res.users',
                                 string='Finance Approved By', readonly=True,
                                 help='Finance user who approved the requisition.')
    finance_approval_date = fields.Date(string='Finance Approval Date',
                                        readonly=True,
                                        help='Date of Finance approval')
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
    can_manager_approve = fields.Boolean(
        compute='_compute_can_manager_approve',
        string='Can Manager Approve'
    )
    can_ra_approve = fields.Boolean(
        compute='_compute_can_ra_approve',
        string='Can RA Approve'
    )
    can_finance_approve = fields.Boolean(
        compute='_compute_can_finance_approve',
        string='Can Finance Approve'
    )
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
    state = fields.Selection([
        ('new', 'New'),
        ('waiting_manager_approval', 'Waiting Manager Approval'),
        ('waiting_ra_approval', 'Waiting Revenue Assurance Approval'),
        ('waiting_finance_approval', 'Waiting Finance Approval'),
        ('approved', 'Approved'),
        ('purchase_order_created', 'Purchase Order Created'),
        ('received', 'Received'),
        ('cancelled', 'Cancelled'),
        ('waiting_head_approval', 'Waiting Finance Approval'),
    ], default='new', copy=False, tracking=True)

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

    def _check_group(self, xml_id):
        try:
            group = self.env.ref(xml_id, raise_if_not_found=False)
            return bool(group and group in self.env.user.groups_id)
        except Exception:
            return False

    def _compute_can_manager_approve(self):
        current_user = self.env.user
        is_admin = current_user.has_group('employee_purchase_requisition.material_category_admin_group') or self.env.is_superuser()
        is_mgr_group = current_user.has_group('employee_purchase_requisition.material_category_manager_group')
        for rec in self:
            is_parent = bool(
                rec.employee_id and rec.employee_id.parent_id and rec.employee_id.parent_id.user_id == current_user
            )
            is_dept_manager = bool(
                rec.dept_id and rec.dept_id.manager_id and rec.dept_id.manager_id.user_id == current_user
            )
            rec.can_manager_approve = is_admin or is_mgr_group or is_parent or is_dept_manager

    def _compute_can_ra_approve(self):
        current_user = self.env.user
        is_admin = current_user.has_group('employee_purchase_requisition.material_category_admin_group') or self.env.is_superuser()
        is_ra = (
            current_user.has_group('employee_purchase_requisition.material_category_ra_group')
            or self._check_group('bxi_equitable_benefit.group_eb_revenue_assurance')
        )
        for rec in self:
            rec.can_ra_approve = is_admin or is_ra

    def _compute_can_finance_approve(self):
        current_user = self.env.user
        is_admin = current_user.has_group('employee_purchase_requisition.material_category_admin_group') or self.env.is_superuser()
        is_finance = (
            current_user.has_group('employee_purchase_requisition.material_category_finance_group')
            or self._check_group('bxi_equitable_benefit.group_eb_finance')
        )
        for rec in self:
            rec.can_finance_approve = is_admin or is_finance

    def action_confirm_requisition(self):
        """Function to confirm purchase requisition with respective company details and submit to Manager"""
        for rec in self:
            if not rec.requisition_order_ids:
                raise ValidationError("Please add at least one product requisition line before confirming.")
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
            rec.write({
                'state': 'waiting_manager_approval',
                'confirm_id': rec.env.uid,
                'confirmed_date': fields.Date.today(),
            })
            rec.message_post(body=f"Requisition confirmed by {rec.env.user.name} and submitted for Manager approval.")

    def action_manager_approval(self):
        """Approval from Manager -> Moves to Waiting Revenue Assurance Approval"""
        for rec in self:
            if not rec.can_manager_approve:
                raise ValidationError("Only the reporting manager, department manager, or an authorized manager/admin can approve at this stage.")
            rec.write({
                'state': 'waiting_ra_approval',
                'manager_id': rec.env.uid,
                'manager_approval_date': fields.Date.today(),
                'department_approval_date': fields.Date.today(),
            })
            rec.message_post(body=f"Requisition approved by Manager ({rec.env.user.name}) and submitted for Revenue Assurance approval.")

    def action_manager_cancel(self):
        """Rejection by Manager"""
        for rec in self:
            if not rec.can_manager_approve:
                raise ValidationError("Only the reporting manager, department manager, or an authorized manager/admin can reject at this stage.")
            emp_id = rec.env.user.employee_id.id if rec.env.user.employee_id else False
            rec.write({
                'state': 'cancelled',
                'rejected_user_id': emp_id,
                'reject_date': fields.Date.today(),
            })
            rec.message_post(body=f"Requisition rejected by Manager ({rec.env.user.name}).")

    def action_ra_approval(self):
        """Approval from Revenue Assurance -> Moves to Waiting Finance Approval"""
        for rec in self:
            if not rec.can_ra_approve:
                raise ValidationError("Only Revenue Assurance team or an administrator can approve at this stage.")
            rec.write({
                'state': 'waiting_finance_approval',
                'ra_id': rec.env.uid,
                'ra_approval_date': fields.Date.today(),
            })
            rec.message_post(body=f"Requisition approved by Revenue Assurance ({rec.env.user.name}) and submitted for Finance approval.")

    def action_ra_cancel(self):
        """Rejection by Revenue Assurance"""
        for rec in self:
            if not rec.can_ra_approve:
                raise ValidationError("Only Revenue Assurance team or an administrator can reject at this stage.")
            emp_id = rec.env.user.employee_id.id if rec.env.user.employee_id else False
            rec.write({
                'state': 'cancelled',
                'rejected_user_id': emp_id,
                'reject_date': fields.Date.today(),
            })
            rec.message_post(body=f"Requisition rejected by Revenue Assurance ({rec.env.user.name}).")

    def action_finance_approval(self):
        """Approval from Finance -> Moves to Approved"""
        for rec in self:
            if not rec.can_finance_approve:
                raise ValidationError("Only the Finance team or an administrator can approve at this stage.")
            rec.write({
                'state': 'approved',
                'finance_id': rec.env.uid,
                'finance_approval_date': fields.Date.today(),
                'requisition_head_id': rec.env.uid,
                'approval_date': fields.Date.today(),
            })
            rec.message_post(body=f"Requisition approved by Finance ({rec.env.user.name}). Purchase Order can now be created.")
            template = rec.env.ref(
                'employee_purchase_requisition.email_template_requisition_approved',
                raise_if_not_found=False
            )
            if template:
                template.send_mail(rec.id, force_send=True)

    def action_finance_cancel(self):
        """Rejection by Finance"""
        for rec in self:
            if not rec.can_finance_approve:
                raise ValidationError("Only the Finance team or an administrator can reject at this stage.")
            emp_id = rec.env.user.employee_id.id if rec.env.user.employee_id else False
            rec.write({
                'state': 'cancelled',
                'rejected_user_id': emp_id,
                'reject_date': fields.Date.today(),
            })
            rec.message_post(body=f"Requisition rejected by Finance ({rec.env.user.name}).")

    def action_reset_to_draft(self):
        """Reset cancelled requisition to draft (new)"""
        for rec in self:
            rec.write({
                'state': 'new',
            })
            rec.message_post(body=f"Requisition reset to New by {rec.env.user.name}.")

    def action_department_approval(self):
        return self.action_manager_approval()

    def action_department_cancel(self):
        return self.action_manager_cancel()

    def action_head_approval(self):
        return self.action_finance_approval()

    def action_head_cancel(self):
        return self.action_finance_cancel()

    def action_create_purchase_order(self):
        """Create purchase order and internal transfer with respective company details following standard purchasing flow."""
        for req in self:
            if req.state != 'approved':
                raise ValidationError("Purchase Order can only be created once the requisition has been approved by Finance.")
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
