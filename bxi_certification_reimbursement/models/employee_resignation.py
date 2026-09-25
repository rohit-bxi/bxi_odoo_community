from odoo import models, api


class EmployeeResignation(models.Model):
    _inherit = 'employee.resignation'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered(lambda r: r.state == 'submitted')._refuse_certification_claims()
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals.get('state') == 'submitted':
            self._refuse_certification_claims()
        return res

    def _refuse_certification_claims(self):
        """Employees serving notice are not eligible for certification reimbursement."""
        if not self:
            return
        requests = self.env['bxi.certification.request'].sudo().search([
            ('employee_id', 'in', self.employee_id.ids),
        ])
        requests._refuse_for_resignation()
