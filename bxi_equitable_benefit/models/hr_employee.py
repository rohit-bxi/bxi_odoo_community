from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    eb_annual_component_a = fields.Monetary(
        readonly=False, related='version_id.eb_annual_component_a', inherited=True, groups='hr.group_hr_user')
    eb_assignment_ids = fields.One2many('bxi.eb.assignment', 'employee_id', string='Work Pattern Assignments')
    eb_current_assignment_id = fields.Many2one(
        'bxi.eb.assignment', string='Current Work Pattern', compute='_compute_eb_current_assignment')
    eb_assignment_count = fields.Integer(compute='_compute_eb_counts')
    eb_payout_count = fields.Integer(compute='_compute_eb_counts')

    def _compute_eb_current_assignment(self):
        today = fields.Date.context_today(self)
        for employee in self:
            employee.eb_current_assignment_id = employee.eb_assignment_ids.filtered(
                lambda a: a.state == 'approved' and a.date_from <= today and (not a.date_to or a.date_to >= today)
            )[:1]

    def _compute_eb_counts(self):
        Assignment = self.env['bxi.eb.assignment']
        Payout = self.env['bxi.eb.payout']
        for employee in self:
            employee.eb_assignment_count = Assignment.search_count([('employee_id', '=', employee.id)])
            employee.eb_payout_count = Payout.search_count([('employee_id', '=', employee.id)])

    def action_open_eb_assignments(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('bxi_equitable_benefit.action_bxi_eb_assignment')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action

    def action_open_eb_payouts(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('bxi_equitable_benefit.action_bxi_eb_payout')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action
