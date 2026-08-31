# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class ResCountry(models.Model):
    _inherit = 'res.country'

    country_code_3 = fields.Char(
        string='Country Code(3 Alphabet)',
        size=3,
        required=True,
    )

    @api.onchange('country_code_3')
    def _onchange_country_code_3(self):
        if self.country_code_3:
            self.country_code_3 = self.country_code_3.upper()

    @api.constrains('country_code_3')
    def _check_country_code_3(self):
        for record in self:
            code = (record.country_code_3 or '').strip()
            if len(code) != 3 or not code.isalpha():
                raise ValidationError(_("Country Code(3 Alphabet) is required and must contain exactly 3 alphabetic characters."))
