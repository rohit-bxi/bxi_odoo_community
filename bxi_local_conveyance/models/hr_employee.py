from dateutil.relativedelta import relativedelta

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
    conveyance_regular_location_id = fields.Many2one(
        'hr.work.location', string='Regular Office', groups='hr.group_hr_user', tracking=True,
        help="Local Conveyance: the employee's regular office. Working from another local office starts an "
             "assignment, covered for the first two months only. Change it on a permanent transfer.")
    conveyance_flexi_fuel = fields.Boolean(
        string='Fuel via Flexi Basket', groups='hr.group_hr_user', tracking=True,
        help="Local Conveyance: petrol for the employee's vehicle is reimbursed through the flexi basket. Their "
             "personal vehicle claims are reviewed by HR, so that the same bill is not claimed twice.")

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

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        # The office an employee joins is their regular office.
        for employee in employees.sudo().filtered(lambda emp: not emp.conveyance_regular_location_id):
            employee.conveyance_regular_location_id = employee.work_location_id
        return employees

    def write(self, vals):
        res = super().write(vals)
        if {'work_location_id', 'conveyance_regular_location_id'} & vals.keys():
            self._sync_conveyance_office_assignment()
        return res

    def _sync_conveyance_office_assignment(self):
        """Clause 8: working from a local office other than the regular one starts an assignment, coming back to
        the regular office (or making the new office the regular one) ends it."""
        Assignment = self.env['bxi.conveyance.office.assignment'].sudo()
        today = fields.Date.context_today(self)
        for employee in self.sudo():
            regular = employee.conveyance_regular_location_id
            if not regular:
                continue
            current = employee.work_location_id
            away = current if current and current != regular else current.browse()
            running = Assignment.search([
                ('employee_id', '=', employee.id), ('date_from', '<=', today),
                '|', ('date_to', '=', False), ('date_to', '>=', today),
            ])
            ended = running.filtered(lambda rec: rec.work_location_id != away)
            for assignment in ended:
                assignment.date_to = max(assignment.date_from, today - relativedelta(days=1))
            if away and not running - ended:
                Assignment.create({
                    'employee_id': employee.id,
                    'work_location_id': away.id,
                    'date_from': today,
                    'note': self.env._("Started when the work location changed from the regular office %(office)s.",
                                       office=regular.name),
                })
