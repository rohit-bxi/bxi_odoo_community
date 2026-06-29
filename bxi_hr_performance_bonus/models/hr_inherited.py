from odoo import models, fields, _,api
# pyrefly: ignore [missing-import]
from datetime import date

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    appraisal_count = fields.Integer(
        string="Performance/Bonus",
        compute="_compute_appraisal_count_1"
    )
    appraisal_ids = fields.One2many('hr.employee.appraisal', 'employee_id')


    @api.depends('appraisal_ids')
    def _compute_appraisal_count_1(self):
        read_group_result = self.env['hr.employee.appraisal'].with_context(active_test=False)._read_group([('employee_id', 'in', self.ids)], ['employee_id'], ['__count'])
        result = {employee.id: count for employee, count in read_group_result}
        for employee in self:
            employee.appraisal_count = result.get(employee.id, 0)


    def action_open_appraisals(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': 'Performance / Bonus',
            'res_model': 'hr.employee.appraisal',
            'view_mode': 'list,form',
            'domain': [
                ('employee_id', '=', self.id)
            ],
            'context': {
                'default_employee_id': self.id,
                'active_test': False,
            },
            'target': 'current',
        }


class BaseDocumentLayout(models.TransientModel):
    _inherit = 'base.document.layout'

    street2 = fields.Char(related='company_id.street2', readonly=True)
    city = fields.Char(related='company_id.city', readonly=True)
    zip = fields.Char(related='company_id.zip', readonly=True)
    state_id = fields.Many2one('res.country.state', related='company_id.state_id', readonly=True)
    country_id = fields.Many2one('res.country', related='company_id.country_id', readonly=True)
    company_registry = fields.Char(related='company_id.company_registry', readonly=True)