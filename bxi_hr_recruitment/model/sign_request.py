from odoo import models

class SignRequest(models.Model):
    _inherit = 'sign.request'

    def write(self, vals):
        res = super().write(vals)

        for record in self:
            # Trigger only when state changes to signed
            if vals.get('state') == 'signed':

                applicant = self.env['hr.applicant'].search([
                    ('sign_request_id', '=', record.id)
                ], limit=1)

                if applicant and applicant.hr_user_id and applicant.hr_user_id.partner_id:
                    applicant.message_post(
                        body="✅ Offer letter signed by Reporting Manager",
                        partner_ids=[applicant.hr_user_id.partner_id.id]
                    )

        return res