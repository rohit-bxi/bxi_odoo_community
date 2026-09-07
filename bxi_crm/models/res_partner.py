# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    customer_type = fields.Selection(
        selection=[
            ('prospect', 'Prospect'),
            ('customer', 'Customer'),
        ],
        string='Customer Type',
        default='prospect',
        tracking=True,
    )

    @api.constrains('vat')
    def _check_unique_gstin(self):
        """Prevent duplicate GSTIN / VAT on partners."""
        for rec in self:
            if not rec.vat or not rec.vat.strip():
                continue
            vat_clean = rec.vat.strip()
            # Search for any other partner having the same GSTIN/VAT
            domain = [
                ('id', '!=', rec.id),
                ('vat', '=ilike', vat_clean),
            ]
            duplicate = self.search(domain, limit=1)
            if duplicate:
                raise ValidationError(_(
                    "The GSTIN '%(gstin)s' is already mapped with partner '%(name)s' (ID: %(id)s).\n"
                    "Duplicate GSTIN numbers are not allowed to be created or updated."
                ) % {
                    'gstin': rec.vat,
                    'name': duplicate.display_name or duplicate.name,
                    'id': duplicate.id,
                })

