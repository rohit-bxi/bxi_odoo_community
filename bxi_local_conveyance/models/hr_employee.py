from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    conveyance_travel_plan_id = fields.Many2one(
        'bxi.conveyance.travel.plan', string='Conveyance Travel Plan',
        compute='_compute_conveyance_travel_plan_id', groups='hr.group_hr_user',
        help="From the band level (E-grade) of the employee.",
    )
    is_sales_team = fields.Boolean(
        string='Sales Team', compute='_compute_is_sales_team', groups='hr.group_hr_user')

    @api.depends('band_level', 'is_band_set')
    def _compute_conveyance_travel_plan_id(self):
        TravelPlan = self.env['bxi.conveyance.travel.plan']
        for rec in self:
            rec.conveyance_travel_plan_id = TravelPlan._get_for_band(rec.band_level) if rec.is_band_set else False

    @api.depends('department_id.is_sales_team', 'department_id.parent_path')
    def _compute_is_sales_team(self):
        for rec in self:
            department = rec.department_id
            ancestors = self.env['hr.department'].browse(
                int(dep_id) for dep_id in (department.parent_path or '').split('/') if dep_id)
            rec.is_sales_team = any(ancestors.mapped('is_sales_team'))
