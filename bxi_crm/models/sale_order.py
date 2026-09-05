# -*- coding: utf-8 -*-

from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        """When a Sale Order is confirmed, mark the partner as 'customer'."""
        result = super().action_confirm()
        for order in self:
            if order.partner_id:
                order.partner_id.sudo().write({'customer_type': 'customer'})
        return result
