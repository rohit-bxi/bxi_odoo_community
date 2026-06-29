from odoo import models, fields, api


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    inv_months = fields.Integer(string="Months", default=1)

    @api.depends(
        "display_type",
        "move_id",
        "quantity",
        "discount",
        "price_unit",
        "tax_ids",
        "currency_id",
        "product_id",
        "partner_id",
        "inv_months",
    )
    def _compute_totals(self):
        """
        Standard logic with inv_months in depends.
        The months multiplication is applied in:
        account.move._prepare_product_base_line_for_taxes_computation()
        """
        AccountTax = self.env["account.tax"]
        for line in self:
            if (
                line.display_type not in ("product", "cogs", "non_deductible_product", "non_deductible_product_total")
                or not line.move_id
            ):
                line.price_total = line.price_subtotal = False
                continue

            company = line.company_id or self.env.company
            base_line = line.move_id._prepare_product_base_line_for_taxes_computation(line)

            AccountTax._add_tax_details_in_base_line(base_line, company)
            AccountTax._round_base_lines_tax_details([base_line], company)

            line.price_subtotal = base_line["tax_details"]["total_excluded_currency"]
            line.price_total = base_line["tax_details"]["total_included_currency"]

    # ---------- IMPORTANT: refresh tax/payment-term lines + residual ----------
    def _months_refresh_move_dynamic_lines(self):
        moves = self.mapped("move_id").filtered(
            lambda m: m and m.state == "draft" and m.is_invoice(include_receipts=True)
        )
        if not moves:
            return

        for move in moves:
            # Odoo 19 standard way
            if hasattr(move, "_sync_dynamic_lines"):
                container = {"records": move}
                with move._sync_dynamic_lines(container):
                    # no-op; entering/exiting triggers recomputation if deltas exist
                    pass
            else:
                # Fallback for safety
                if hasattr(move, "_compute_tax_totals"):
                    move._compute_tax_totals()
                if hasattr(move, "_compute_amount"):
                    move._compute_amount()

    @api.onchange("inv_months")
    def _onchange_inv_months(self):
        self._months_refresh_move_dynamic_lines()
        self._months_force_full_recompute()

    def write(self, vals):
        res = super().write(vals)
        if "inv_months" in vals:
            self._months_refresh_move_dynamic_lines()
            self._months_force_full_recompute()
            moves = self.mapped("move_id").filtered(
                lambda m: m and m.state == "draft" and m.is_invoice(include_receipts=True)
            )

            if moves:
                # First refresh tax/payment term lines
                moves._compute_tax_totals()

                if hasattr(moves, "_sync_dynamic_lines"):
                    container = {"records": moves}
                    with moves._sync_dynamic_lines(container):
                        pass
                moves._compute_amount()
        return res

    def _months_force_full_recompute(self):
        moves = self.mapped("move_id").filtered(
            lambda m: m and m.state == "draft" and m.is_invoice(include_receipts=True)
        )
        if not moves:
            return

        for move in moves:
            # 1) Ensure tax totals updated
            if hasattr(move, "_compute_tax_totals"):
                move._compute_tax_totals()

            # 2) Force regeneration of payment term / receivable lines
            # This is the key for Amount Due.
            if hasattr(move, "_sync_dynamic_lines"):
                container = {"records": move}
                with move._sync_dynamic_lines(container):
                    # Force a detectable change by touching invoice_line_ids write context,
                    # exiting the context triggers rebuild
                    pass

            # 3) Recompute amounts (residual/amount_due depends on payment_term lines)
            if hasattr(move, "_compute_amount"):
                move._compute_amount()

