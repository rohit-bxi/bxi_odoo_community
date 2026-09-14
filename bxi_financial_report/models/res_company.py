# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ResCompany(models.Model):
    _inherit = 'res.company'

    main_company_id = fields.Many2one(
        'res.company',
        string='Grouped Company',
        index=True,
        domain="[('id', '!=', id)]",
        help="When the selected Grouped Company is activated in the company switcher, this company will also be automatically selected."
    )
    grouped_company_ids = fields.One2many(
        'res.company',
        'main_company_id',
        string='Grouped Sub-Companies'
    )


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        result = super().session_info()
        user_companies = result.get('user_companies')
        if user_companies and 'allowed_companies' in user_companies:
            allowed = user_companies['allowed_companies']
            company_ids = [int(cid) for cid in allowed.keys()]
            companies = self.env['res.company'].sudo().browse(company_ids)
            comp_map = {c.id: c for c in companies}
            for cid_str, cdata in allowed.items():
                cid = int(cid_str)
                comp = comp_map.get(cid)
                if comp:
                    cdata['main_company_id'] = comp.main_company_id.id if comp.main_company_id else False
                    cdata['grouped_company_ids'] = comp.grouped_company_ids.filtered(lambda c: c.id in comp_map).ids
        return result
