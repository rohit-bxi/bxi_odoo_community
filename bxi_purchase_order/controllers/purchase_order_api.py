from odoo import http, fields
from odoo.http import request
from datetime import datetime

class PurchaseOrderAPI(http.Controller):

    @http.route('/api/purchase/create', type='json', auth='public', methods=['POST'], csrf=False)
    def create_purchase_order(self, **params):
        try:
            data = params.get('params', params)

            fixed_partner_id = 11
            fixed_product_id = 65

            order_lines = data.get('order_line')

            if not order_lines:
                return {"status": "error", "message": "order_line is required"}

            # =========================
            #  VALIDATE PARTNER (if sent)
            # =========================
            payload_partner_id = data.get('partner_id')

            if payload_partner_id and payload_partner_id != fixed_partner_id:
                return {
                    "status": "error",
                    "message": f"Only partner_id {fixed_partner_id} allowed"
                }

            # =========================
            #  GET FIXED PARTNER
            # =========================
            partner = request.env['res.partner'].sudo().browse(fixed_partner_id)

            if not partner.exists():
                return {"status": "error", "message": "Fixed vendor not found"}

            # =========================
            #  GET FIXED PRODUCT
            # =========================
            product = request.env['product.product'].sudo().browse(fixed_product_id)

            if not product.exists():
                return {"status": "error", "message": "Fixed product not found"}

            # =========================
            #  PREPARE ORDER LINES
            # =========================
            lines = []

            for line in order_lines:
                qty = line.get('product_qty')
                payload_product_id = line.get('product_id')

                #  Validate product_id if sent
                if payload_product_id and payload_product_id != fixed_product_id:
                    return {
                        "status": "error",
                        "message": f"Only product_id {fixed_product_id} allowed"
                    }

                if not qty:
                    return {"status": "error", "message": "product_qty is required"}

                lines.append((0, 0, {
                    'product_id': product.id,
                    'name': product.display_name,
                    'product_qty': qty,
                    'price_unit': product.standard_price,
                    'date_planned': fields.Datetime.now(),
                }))

            # =========================
            #  DATE
            # =========================
            date_order = data.get('date_order')
            if date_order:
                date_order = datetime.strptime(date_order, "%Y-%m-%d %H:%M:%S")
            else:
                date_order = fields.Datetime.now()

            # =========================
            #  CREATE PO
            # =========================
            po_vals = {
                'partner_id': partner.id,
                'date_order': date_order,
                'origin': data.get('origin'),
                'order_line': lines,
            }

            po = request.env['purchase.order'].sudo().create(po_vals)

            # =========================
            #  CONFIRM PO
            # =========================
            if data.get('confirm_po', True):
                po.button_confirm()

            # =========================
            #  RESPONSE
            # =========================
            return {
                "status": "success",
                "message": "Purchase Order Created",
                "data": {
                    "po_id": po.id,
                    "po_name": po.name,
                    "state": po.state,
                    "partner_id": po.partner_id.id,
                    "product_id": fixed_product_id,
                    "price_subtotal": po.order_line[0].price_subtotal,
                    "total": po.amount_total
                }
            }

        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }

    @http.route('/api/purchase/read', type='json', auth='public', methods=['POST'], csrf=False)
    def get_purchase_orders(self, **params):
        try:
            data = params.get('params', params)

            po_id = data.get('po_id')  # optional (single PO)

            domain = []

            # =========================
            # FILTER BY PO ID (OPTIONAL)
            # =========================
            if po_id:
                domain.append(('id', '=', po_id))

            # =========================
            # FETCH DATA
            # =========================
            pos = request.env['purchase.order'].sudo().search(domain)

            if not pos:
                return {
                    "status": "error",
                    "message": "No Purchase Orders found"
                }

            result = []

            for po in pos:
                lines = []

                for line in po.order_line:
                    lines.append({
                        "product_id": line.product_id.id,
                        "product_name": line.product_id.display_name,
                        "qty": line.product_qty,
                        "price_unit": line.price_unit,
                        "price_subtotal": line.price_subtotal
                    })

                result.append({
                    "po_id": po.id,
                    "po_name": po.name,
                    "state": po.state,
                    "partner_id": po.partner_id.id,
                    "partner_name": po.partner_id.name,
                    "date_order": po.date_order,
                    "amount_total": po.amount_total,
                    "order_lines": lines
                })

            return {
                "status": "success",
                "count": len(result),
                "data": result
            }

        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }