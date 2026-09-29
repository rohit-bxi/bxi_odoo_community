import base64

from odoo import Command, api, models


class SignRequest(models.Model):
    _inherit = 'sign.request'

    def _sign(self):
        res = super()._sign()
        for request in self:
            document = request.reference_doc
            if not document:
                continue
            if document._name == 'bxi.training.request':
                document.sudo()._on_form_signed()
            elif document._name == 'bxi.training.agreement':
                document.sudo()._on_esigned()
        return res

    @api.model
    def _trn_create_for_pdf(self, pdf, name, partner, reference, reference_doc, subject):
        """Create a one-signer request from a rendered PDF, signed at the bottom of its last page."""
        SignTemplate = self.env['sign.template'].sudo()
        template_info = SignTemplate.create_from_attachment_data(
            [{'name': name, 'datas': base64.b64encode(pdf)}], active=False)
        template = SignTemplate.browse(template_info['id'])
        document = template.document_ids[:1]
        role = self.env.ref('sign.sign_item_role_default')
        last_page = max(document.num_pages, 1)
        self.env['sign.item'].sudo().create([
            {
                'document_id': document.id,
                'type_id': self.env.ref('sign.sign_item_type_signature').id,
                'responsible_id': role.id,
                'page': last_page,
                'posX': 0.08, 'posY': 0.78, 'width': 0.30, 'height': 0.06,
            },
            {
                'document_id': document.id,
                'type_id': self.env.ref('sign.sign_item_type_date').id,
                'responsible_id': role.id,
                'page': last_page,
                'posX': 0.60, 'posY': 0.80, 'width': 0.20, 'height': 0.03,
            },
        ])
        return self.sudo().create({
            'template_id': template.id,
            'reference': reference,
            'reference_doc': f"{reference_doc._name},{reference_doc.id}",
            'subject': subject,
            'request_item_ids': [Command.create({'partner_id': partner.id, 'role_id': role.id})],
        })
