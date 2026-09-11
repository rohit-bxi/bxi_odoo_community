# -*- coding: utf-8 -*-

from odoo import models, fields, api


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    months = fields.Integer(string="Months", default=1)

    def _prepare_base_line_for_taxes_computation(self, **kwargs):
        """
        Core hook: tax and totals base quantity uses qty * months.
        """
        base_line = super()._prepare_base_line_for_taxes_computation(**kwargs)
        months = self.months if self.months and self.months > 0 else 1
        qty = base_line.get("quantity", self.product_uom_qty or 0.0) or 0.0
        base_line["quantity"] = qty * months
        return base_line

    @api.depends("product_uom_qty", "discount", "price_unit", "tax_ids", "months")
    def _compute_amount(self):
        super()._compute_amount()

    @api.depends("price_subtotal", "product_uom_qty", "months")
    def _compute_price_reduce_taxexcl(self):
        for line in self:
            months = line.months if line.months and line.months > 0 else 1
            total_qty = (line.product_uom_qty or 0.0) * months
            line.price_reduce_taxexcl = line.price_subtotal / total_qty if total_qty else 0.0

    @api.depends("price_total", "product_uom_qty", "months")
    def _compute_price_reduce_taxinc(self):
        for line in self:
            months = line.months if line.months and line.months > 0 else 1
            total_qty = (line.product_uom_qty or 0.0) * months
            line.price_reduce_taxinc = line.price_total / total_qty if total_qty else 0.0

    @api.onchange("months")
    def _onchange_months(self):
        self._compute_amount()
        if self.order_id:
            self.order_id._compute_amounts()

    def _prepare_invoice_line(self, **optional_values):
        """
        Pass months value to invoice line (inv_months).
        """
        res = super()._prepare_invoice_line(**optional_values)
        if not self.display_type:
            res["inv_months"] = self.months if self.months and self.months > 0 else 1
        return res
