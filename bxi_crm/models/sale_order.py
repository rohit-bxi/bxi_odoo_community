# -*- coding: utf-8 -*-

from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        """When a Sale Order is confirmed, mark the partner as 'customer'."""
        result = super().action_confirm()
        for order in self:
            if order.partner_id:
                if order.partner_id.customer_type == 'vendor':
                    order.partner_id.sudo().write({'customer_type': 'customer_and_vendor'})
                elif order.partner_id.customer_type not in ('customer', 'customer_and_vendor'):
                    order.partner_id.sudo().write({'customer_type': 'customer'})
        return result
