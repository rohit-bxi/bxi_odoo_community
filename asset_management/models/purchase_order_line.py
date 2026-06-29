from odoo import models, fields

class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    is_a_assets = fields.Boolean(string="Is an Asset")


from odoo import models, api

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def button_confirm(self):
        res = super().button_confirm()

        Asset = self.env['asset.management']

        for order in self:
            for line in order.order_line:
                if not line.is_a_assets:
                    continue

                # Search existing asset (adjust domain if needed)
                asset = Asset.search([
                    ('product_id', '=', line.product_id.id),
                    ('model_type', '=', 'multiple')
                ], limit=1)

                if asset:
                    # Asset exists → increase stock
                    asset.initial_stock += line.product_qty
                else:
                    # Create new asset
                    Asset.create({
                        'name': line.product_id.display_name,
                        'product_id': line.product_id.id,
                        'model_type': 'multiple',
                        'initial_stock': line.product_qty,
                    })

        return res
