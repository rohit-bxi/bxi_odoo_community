from dateutil.relativedelta import relativedelta

from odoo import fields, models

from .salary_advance import RECOVERY_STATES


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    sa_advance_ids = fields.One2many('bxi.salary.advance', 'employee_id', string='Salary Advances')
    sa_advance_count = fields.Integer(
        string='Salary Advance Count', compute='_compute_sa_advances',
        groups='bxi_salary_advance.group_salary_advance_hr,bxi_salary_advance.group_salary_advance_finance')
    sa_outstanding_balance = fields.Monetary(
        string='Outstanding Salary Advance', compute='_compute_sa_advances', currency_field='currency_id',
        groups='bxi_salary_advance.group_salary_advance_hr,bxi_salary_advance.group_salary_advance_finance')

    def _compute_sa_advances(self):
        Advance = self.env['bxi.salary.advance'].sudo()
        for employee in self:
            advances = Advance.search([('employee_id', '=', employee.id)])
            employee.sa_advance_count = len(advances)
            employee.sa_outstanding_balance = sum(
                advances.filtered(lambda a: a.state in RECOVERY_STATES).mapped('amount_balance'))

    def _sa_get_monthly_salary(self):
        """Current monthly salary, built like the India: Regular Pay structure (BASIC + STD + SPL)."""
        self.ensure_one()
        version = self.version_id
        basic = version.wage or self.l10n_in_basic_salary_amount or 0.0
        basis = self.env['ir.config_parameter'].sudo().get_param('bxi_salary_advance.salary_basis', 'gross')
        if basis == 'basic':
            return basic
        hra = version.hra or self.l10n_in_hra or 0.0
        return basic + hra + (self.l10n_in_fixed_allowance or 0.0)

    def _sa_get_service_start(self):
        """Start of the continuous employment with BXITech."""
        self.ensure_one()
        return self.emp_date_of_joining or self._get_first_contract_date()

    def _sa_is_serving_notice(self):
        self.ensure_one()
        return bool(self.env['employee.resignation'].sudo().search_count([
            ('employee_id', '=', self.id), ('state', 'in', ('submitted', 'approved')),
        ], limit=1))

    def _sa_is_eligible_type(self):
        """The policy applies to full-time employees: contractors, trainees and the like are excluded."""
        self.ensure_one()
        value = self.env['ir.config_parameter'].sudo().get_param(
            'bxi_salary_advance.eligible_employee_types', 'employee,worker')
        types = {part.strip() for part in (value or '').split(',') if part.strip()}
        return self.sudo().employee_type in types

    def _sa_done_payslips(self, date_from, date_to):
        """Confirmed payslips of the employee overlapping the period."""
        self.ensure_one()
        return self.env['hr.payslip'].sudo().search([
            ('employee_id', '=', self.id),
            ('state', '=', 'done'),
            ('credit_note', '=', False),
            ('date_from', '<=', date_to),
            ('date_to', '>=', date_from),
        ])

    def _sa_get_last_payroll_period(self):
        """Period of the last payroll cycle confirmed for the employee's company, or None."""
        self.ensure_one()
        last = self.env['hr.payslip'].sudo().search([
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'done'),
            ('credit_note', '=', False),
            ('date_to', '<=', fields.Date.context_today(self)),
        ], order='date_to desc', limit=1)
        return (last.date_from, last.date_to) if last else None

    def _sa_salary_processed_in_last_payroll(self):
        """The confirmed payslip that paid the employee in the last payroll cycle, if any."""
        self.ensure_one()
        period = self._sa_get_last_payroll_period()
        if not period:
            return self.env['hr.payslip']
        return self._sa_done_payslips(*period).filtered(lambda slip: slip.net_wage > 0)[:1]

    def _sa_first_open_payroll_month(self, day):
        """First day of the first month, from ``day`` on, whose payroll is not confirmed yet."""
        self.ensure_one()
        month = day.replace(day=1)
        for _attempt in range(12):
            if not self._sa_done_payslips(month, month + relativedelta(months=1, days=-1)):
                break
            month += relativedelta(months=1)
        return month

    def _sa_get_policy_status(self, create=False):
        """Salary Advance Policy of the company and the employee's acknowledgement of its current version.

        :param create: ask the employee to acknowledge when no request exists yet
        :return: dict with ``policy``, ``ack`` and ``required`` (acknowledgement still missing)
        """
        self.ensure_one()
        policy = self.company_id.sudo().sa_policy_id
        Ack = self.env['hr.policy.acknowledgement'].sudo()
        version = policy.current_version_id
        if not (policy and version and policy.requires_acknowledgement):
            return {'policy': policy, 'ack': Ack, 'required': False}
        ack = Ack.search([('employee_id', '=', self.id), ('version_id', '=', version.id)], limit=1)
        if not ack and create and self.user_id:
            ack = version.sudo()._create_acknowledgements(self)[:1]
        return {'policy': policy, 'ack': ack, 'required': ack.state not in ('acknowledged', 'waived')}

    def action_open_salary_advances(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('bxi_salary_advance.action_bxi_salary_advance')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action
