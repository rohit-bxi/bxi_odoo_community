from odoo import models
 
class SignOcaRequest(models.Model):
    _inherit = 'sign.oca.request'

    def write(self, vals):
        res = super().write(vals)

        for record in self:
            # Trigger when state changes to signed ('2_signed' in sign_oca, 'signed' in standard sign)
            if vals.get('state') in ('2_signed', 'signed'):
                applicant = self.env['hr.applicant'].search([
                    ('sign_request_id', '=', record.id)
                ], limit=1)

                if not applicant and record.record_ref and getattr(record.record_ref, '_name', False) == 'hr.applicant':
                    applicant = record.record_ref

                if applicant and applicant.hr_user_id and applicant.hr_user_id.partner_id:
                    applicant.message_post(
                        body="✅ Offer letter signed by Reporting Manager",
                        partner_ids=[applicant.hr_user_id.partner_id.id]
                    )

        return res