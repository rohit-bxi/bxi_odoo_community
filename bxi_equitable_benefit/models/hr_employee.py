from datetime import timedelta

from odoo import _, fields, models

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

    def _eb_deployment_changed(self, deployment, day, reason):
        """The employee moves onsite / offshore from ``day`` (e.g. an international deputation).

        The approved work pattern carries the old deployment, so its rate may no longer apply.
        Prepare a draft successor with the new deployment and ask Revenue Assurance to review it.
        """
        Assignment = self.env['bxi.eb.assignment'].sudo()
        for employee in self:
            current = Assignment.search([
                ('employee_id', '=', employee.id),
                ('state', '=', 'approved'),
                ('date_from', '<=', day),
                '|', ('date_to', '=', False), ('date_to', '>=', day),
            ], limit=1)
            if not current or current.deployment == deployment:
                continue
            new_label = dict(current._fields['deployment'].selection)[deployment]
            record, note = current, _(
                "%(reason)s: the employee is %(deployment)s from %(day)s. Change this work pattern "
                "to match.", reason=reason, deployment=new_label, day=day)
            if current.date_from < day:
                record = current.copy({
                    'date_from': day,
                    'date_to': current.date_to,
                    'deployment': deployment,
                    'justification': '%s\n%s' % (current.justification or '', reason),
                })
                note = _(
                    "%(reason)s: the employee is %(deployment)s from %(day)s, but %(old)s is approved as "
                    "%(old_deployment)s. Submit and approve this draft, or end %(old)s on %(last)s if the "
                    "new deployment carries no benefit.",
                    reason=reason, deployment=new_label, day=day, old=current.name,
                    old_deployment=dict(current._fields['deployment'].selection)[current.deployment],
                    last=day - timedelta(days=1))
            record.message_post(body=note)
            record._eb_notify_group('bxi_equitable_benefit.group_eb_revenue_assurance',
                                    _("Review the deployment of %s", employee.name), note)

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
