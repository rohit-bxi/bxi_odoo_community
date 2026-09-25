from odoo import models


class SignRequest(models.Model):
    _inherit = 'sign.request'

    def _sign(self):
        res = super()._sign()
        for request in self:
            if request.reference_doc and request.reference_doc._name == 'bxi.service.agreement':
                request.reference_doc.sudo()._on_signed()
        return res
