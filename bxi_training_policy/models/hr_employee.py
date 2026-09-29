from odoo import api, fields, models

from .training_agreement import BINDING_STATES
from .training_recovery import OPEN_STATES as RECOVERY_OPEN_STATES


# Users who see the training figures of the employees.
TRAINING_READ_GROUPS = ('hr.group_hr_user,bxi_training_policy.group_training_hr,'
                        'bxi_training_policy.group_training_finance')


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    trn_request_count = fields.Integer(string='Trainings', compute='_compute_trn_stats', groups=TRAINING_READ_GROUPS)
    trn_bonded_amount = fields.Monetary(
        string='Training Cost Under Agreement', compute='_compute_trn_stats', currency_field='currency_id',
        groups=TRAINING_READ_GROUPS,
        help="Cost of the trainings whose service period is not served yet.",
    )
    trn_bond_end_date = fields.Date(
        string='Training Agreements End', compute='_compute_trn_stats', groups=TRAINING_READ_GROUPS)
    trn_due_amount = fields.Monetary(
        string='Training Dues', compute='_compute_trn_stats', currency_field='currency_id',
        groups=TRAINING_READ_GROUPS)

    def _compute_trn_stats(self):
        Request = self.env['bxi.training.request'].sudo()
        Agreement = self.env['bxi.training.agreement'].sudo()
        Recovery = self.env['bxi.training.recovery'].sudo()
        counts = dict(Request._read_group([('employee_id', 'in', self.ids)], ['employee_id'], ['__count']))
        for employee in self:
            agreements = Agreement.search([('employee_id', '=', employee.id), ('state', 'in', BINDING_STATES)])
            recoveries = Recovery.search([('employee_id', '=', employee.id), ('state', 'in', RECOVERY_OPEN_STATES)])
            employee.trn_request_count = counts.get(employee, 0)
            employee.trn_bonded_amount = sum(agreements.mapped('amount'))
            employee.trn_bond_end_date = max(agreements.filtered('end_date').mapped('end_date'), default=False)
            employee.trn_due_amount = sum(recoveries.mapped('balance'))

    def _trn_has_active_resignation(self):
        self.ensure_one()
        return bool(self.env['employee.resignation'].sudo().search_count([
            ('employee_id', '=', self.id), ('state', 'in', ('submitted', 'approved')),
        ], limit=1))

    def _trn_get_policy_status(self, create=False):
        """Training Policy of the company and the employee's acknowledgement of its current version.

        :param create: ask the employee to acknowledge when no request exists yet
        :return: dict with ``policy``, ``ack`` and ``required`` (acknowledgement still missing)
        """
        self.ensure_one()
        policy = self.company_id.sudo().trn_policy_id
        Ack = self.env['hr.policy.acknowledgement'].sudo()
        version = policy.current_version_id
        if not (policy and version and policy.requires_acknowledgement):
            return {'policy': policy, 'ack': Ack, 'required': False}
        ack = Ack.search([('employee_id', '=', self.id), ('version_id', '=', version.id)], limit=1)
        if not ack and create and self.user_id:
            ack = version.sudo()._create_acknowledgements(self)[:1]
        return {'policy': policy, 'ack': ack, 'required': ack.state not in ('acknowledged', 'waived')}

    @api.model
    def _trn_department_employees(self, user):
        """Employees a Department Head can nominate: their departments, or their direct reports
        when a department has no manager."""
        manager = user.employee_id
        if not manager:
            return self.browse()
        return self.sudo().search([
            ('id', '!=', manager.id),
            '|',
            ('department_id.manager_id', '=', manager.id),
            '&', ('department_id.manager_id', '=', False), ('parent_id', '=', manager.id),
        ])

    def action_open_trainings(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('bxi_training_policy.action_bxi_training_request')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action
