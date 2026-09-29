from odoo import api, fields, models

from .training_agreement import BINDING_STATES
from .training_recovery import OPEN_STATES as RECOVERY_OPEN_STATES
from .training_mixin import HR_GROUP


class EmployeeResignation(models.Model):
    _inherit = 'employee.resignation'

    trn_agreement_ids = fields.Many2many(
        'bxi.training.agreement', string='Training Agreements', compute='_compute_trn_dues')
    trn_recovery_ids = fields.Many2many('bxi.training.recovery', string='Training Recoveries', compute='_compute_trn_dues')
    trn_due_amount = fields.Monetary(string='Training Dues', compute='_compute_trn_dues', currency_field='trn_currency_id')
    trn_currency_id = fields.Many2one(related='company_id.currency_id', string='Training Currency')

    def _compute_trn_dues(self):
        Agreement = self.env['bxi.training.agreement'].sudo()
        Recovery = self.env['bxi.training.recovery'].sudo()
        for resignation in self:
            employee = resignation.employee_id
            last_day = resignation.approved_last_working_day or resignation.last_working_day
            agreements = Agreement.search([
                ('employee_id', '=', employee.id), ('state', 'in', BINDING_STATES),
            ]).filtered(lambda a: a._is_due_on(last_day)) if employee else Agreement
            recoveries = Recovery.search([
                ('employee_id', '=', employee.id), ('state', 'in', RECOVERY_OPEN_STATES),
            ]) if employee else Recovery
            resignation.trn_agreement_ids = agreements
            resignation.trn_recovery_ids = recoveries
            resignation.trn_due_amount = sum(agreements.mapped('amount')) + sum(recoveries.mapped('balance'))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered(lambda r: r.state in ('submitted', 'approved'))._trn_on_notice()
        records.filtered(lambda r: r.state == 'approved')._trn_on_approved()
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals.get('state') in ('submitted', 'approved'):
            self._trn_on_notice()
        if vals.get('state') == 'approved':
            self._trn_on_approved()
        return res

    def _trn_on_notice(self):
        """Trainings not started are cancelled; HR decides on the ones in progress."""
        Request = self.env['bxi.training.request'].sudo()
        for resignation in self:
            requests = Request.search([('employee_id', '=', resignation.employee_id.id)])
            requests._cancel_for_resignation(resignation)
            for request in requests.filtered(lambda r: r.state == 'in_training'):
                request._notify_group(
                    request.company_id.trn_hr_user_id, HR_GROUP,
                    self.env._("Resignation during training: %(employee)s", employee=request.employee_id.name),
                    self.env._("%(training)s is in progress. The service agreement becomes due when the resignation "
                               "is approved.", training=request.training_name))

    def _trn_on_approved(self):
        """Service periods not served on the last working day: the full cost is recovered in the F&F."""
        Agreement = self.env['bxi.training.agreement'].sudo()
        for resignation in self:
            last_day = resignation.approved_last_working_day or resignation.last_working_day
            if not last_day:
                continue
            Agreement.search([
                ('employee_id', '=', resignation.employee_id.id), ('state', 'in', BINDING_STATES),
            ])._action_breach(last_day, resignation)

    def action_open_training_recoveries(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('bxi_training_policy.action_bxi_training_recovery')
        action['domain'] = [('employee_id', '=', self.employee_id.id)]
        return action
