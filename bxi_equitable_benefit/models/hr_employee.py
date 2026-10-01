from odoo import fields, models

PARAM_PREFIX = 'bxi_equitable_benefit.'


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

    def _eb_settle_separation(self, last_day, resignation=False):
        """Settle the Equitable Benefit of separating employees in their Full & Final Settlement."""
        Payout = self.env['bxi.eb.payout'].sudo()
        Assignment = self.env['bxi.eb.assignment'].sudo()
        for employee in self:
            if Assignment.search_count([('employee_id', '=', employee.id), ('state', '=', 'approved')], limit=1):
                Payout._create_fnf_payout(employee, last_day, resignation)

    def get_equitable_benefit_tds(self, amount):
        """Income tax on a lump-sum Equitable Benefit payout (used by the EQB_TDS salary rule).

        The regular monthly TDS covers the annual salary only, so the payout is taxed at the
        employee's marginal slab: tax on the annual income including it, minus tax without it.
        """
        self.ensure_one()
        params = self.env['ir.config_parameter'].sudo()
        if not amount or params.get_param(PARAM_PREFIX + 'payout_tds', 'incremental') != 'incremental':
            return 0.0
        employee = self.sudo()
        annual_income = employee.employee_ctc or (employee.version_id.wage or 0.0) * 12
        tax = employee._compute_annual_tax_new_regime
        return round(max(tax(annual_income + amount) - tax(annual_income), 0.0), 2)
