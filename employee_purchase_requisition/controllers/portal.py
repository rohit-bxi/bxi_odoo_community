# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal


class MaterialRequisitionPortal(CustomerPortal):

    # ---------------------------------------------------------
    # Portal Counter
    # ---------------------------------------------------------
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)

        if 'material_requisition_count' in counters:
            count = request.env['employee.purchase.requisition'].sudo().search_count([
                ('employee_id.user_id', '=', request.env.user.id)
            ])
            values['material_requisition_count'] = count

        return values

    # ---------------------------------------------------------
    # List View
    # ---------------------------------------------------------
    @http.route(['/my/material-requisition'], type='http', auth='user', website=True)
    def portal_material_requisition(self, **kwargs):

        requisitions = request.env['employee.purchase.requisition'].sudo().search([
            ('employee_id.user_id', '=', request.env.user.id)
        ], order='id desc')

        return request.render(
            'employee_purchase_requisition.bxi_purchase_requisition_template',
            {
                'requests': requisitions,
                'page_name': 'material_requisition',
            }
        )

    # ---------------------------------------------------------
    # Detail View (SECURE)
    # ---------------------------------------------------------
    @http.route(['/my/material-requisition/<int:requisition_id>'], type='http', auth='user', website=True)
    def portal_material_requisition_detail(self, requisition_id=None, **kwargs):

        requisition = request.env['employee.purchase.requisition'].sudo().search([
            ('id', '=', requisition_id),
            ('employee_id.user_id', '=', request.env.user.id)
        ])

        if not requisition:
            return request.redirect('/my/material-requisition')

        return request.render(
            'employee_purchase_requisition.requisition_detail_template',
            {
                'requisition': requisition,
                'page_name': 'material_requisition_detail',
            }
        )

    # ---------------------------------------------------------
    # Form View
    # ---------------------------------------------------------
    @http.route('/my/submit-requisition', type='http', auth='user', website=True)
    def requisition_form(self, **kw):

        return request.render(
            'employee_purchase_requisition.material_requisition_form',
            {
                'products': request.env['product.product'].sudo().search([]),
                'customers': request.env['res.partner'].sudo().search([('customer_rank', '>', 0)]),
            }
        )

    # ---------------------------------------------------------
    # Submit Form (FINAL FIXED)
    # ---------------------------------------------------------
    @http.route('/my/material-requisition/submit', type='http', auth='user', website=True, methods=['POST'])
    def submit_requisition(self, **post):

        user = request.env.user
        employee = user.employee_id.sudo()

        # ✅ Validation: employee
        if not employee:
            return request.redirect('/my?error=no_employee')

        # ✅ Required fields
        if not post.get('requisition_date') or not post.get('requisition_deadline'):
            return request.redirect('/my/submit-requisition?error=missing_fields')

        # ✅ Validate req_type
        req_type = post.get('req_type')
        if req_type not in ['internal', 'customer']:
            return request.redirect('/my/submit-requisition?error=invalid_type')

        # ✅ Customer validation
        customer_id = False
        if req_type == 'customer':
            if not post.get('customer_id'):
                return request.redirect('/my/submit-requisition?error=customer_required')
            customer_id = int(post.get('customer_id'))

        # ✅ Get products safely
        products = request.httprequest.form.getlist('product_id[]') or []
        qtys = request.httprequest.form.getlist('quantity[]') or []

        lines = []

        for i in range(min(len(products), len(qtys))):
            try:
                product_id = int(products[i])
                qty = int(qtys[i])
            except:
                continue

            # ✅ Safe validation
            if product_id <= 0 or qty <= 0 or qty > 100000:
                continue

            lines.append((0, 0, {
                'product_id': product_id,
                'quantity': qty,
            }))

        # ❌ No valid product
        if not lines:
            return request.redirect('/my/submit-requisition?error=no_products')

        # ✅ Create requisition
        requisition = request.env['employee.purchase.requisition'].sudo().create({
            'employee_id': employee.id,
            'requisition_date': post.get('requisition_date'),
            'requisition_deadline': post.get('requisition_deadline'),
            'req_type': req_type,
            'customer_id': customer_id,
            'requisition_description': post.get('requisition_description'),
            'requisition_order_ids': lines
        })

        # ✅ Optional: call only if method exists
        if hasattr(requisition, 'action_confirm_requisition'):
            requisition.action_confirm_requisition()

        return request.redirect('/my/material-requisition')