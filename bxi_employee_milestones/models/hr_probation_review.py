# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


# A review starts this many days before the probation end date.
PROBATION_REVIEW_LEAD_DAYS = 15
OPEN_STATES = ('manager_review', 'hr_review')


class HrProbationReview(models.Model):
    _name = 'hr.probation.review'
    _description = 'Probation Review'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'probation_end_date desc, id desc'

    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, readonly=True,
        index=True, ondelete='cascade', tracking=True)
    company_id = fields.Many2one(
        related='employee_id.company_id', store=True, index=True)
    department_id = fields.Many2one(
        related='employee_id.department_id', store=True)
    manager_id = fields.Many2one(
        'hr.employee', string='Reporting Manager',
        related='employee_id.parent_id', store=True, index=True)
    joining_date = fields.Date(
        related='employee_id.emp_date_of_joining', string='Date of Joining')
    probation_end_date = fields.Date(
        string='Probation End Date', required=True, readonly=True, tracking=True)
    state = fields.Selection(
        [
            ('manager_review', 'Waiting Manager'),
            ('hr_review', 'Waiting HR'),
            ('confirmed', 'Confirmed'),
            ('refused', 'Not Confirmed'),
        ],
        string='Status', default='manager_review', required=True, readonly=True,
        tracking=True, index=True, copy=False)
    manager_comments = fields.Text(string='Manager Comments', tracking=True)
    hr_comments = fields.Text(string='HR Comments', tracking=True)
    manager_decision_by = fields.Many2one('res.users', readonly=True, copy=False)
    manager_decision_on = fields.Datetime(readonly=True, copy=False)
    hr_decision_by = fields.Many2one('res.users', readonly=True, copy=False)
    hr_decision_on = fields.Datetime(readonly=True, copy=False)

    _employee_end_date_uniq = models.Constraint(
        'UNIQUE(employee_id, probation_end_date)',
        'A probation review already exists for this employee and probation end date.',
    )

    @api.depends('employee_id')
    def _compute_display_name(self):
        for review in self:
            review.display_name = _('Probation Review - %s', review.employee_id.name)

    # ============================================================
    # SCHEDULED JOB
    # ============================================================

    @api.model
    def _cron_start_probation_reviews(self):
        """Start a review for employees on probation whose end date is at most
        PROBATION_REVIEW_LEAD_DAYS away (or already passed). An employee with
        an open review, or a review for the same end date, is skipped."""
        Employee = self.env['hr.employee'].sudo()
        today = Employee._milestone_today()
        employees = Employee.search([
            ('probation_period', '=', 'yes'),
            ('probation_end_date', '!=', False),
            ('probation_end_date', '<=', today + timedelta(days=PROBATION_REVIEW_LEAD_DAYS)),
        ])
        reviews = self.sudo().search([('employee_id', 'in', employees.ids)])
        open_employees = reviews.filtered(lambda r: r.state in OPEN_STATES).employee_id
        reviewed = {(r.employee_id.id, r.probation_end_date) for r in reviews}
        to_start = employees.filtered(
            lambda e: e not in open_employees and (e.id, e.probation_end_date) not in reviewed)
        new_reviews = self.sudo().create([
            {'employee_id': employee.id, 'probation_end_date': employee.probation_end_date}
            for employee in to_start
        ])
        new_reviews._start_manager_review()
        return new_reviews

    # ============================================================
    # HELPERS
    # ============================================================

    def _is_hr_user(self):
        return self.env.su or self.env.user.has_group('hr.group_hr_user')

    def _check_state(self, *states):
        for review in self:
            if review.state not in states:
                raise UserError(_('This action is not available for a review in status "%s".',
                                  dict(self._fields['state'].selection)[review.state]))

    def _check_manager_access(self):
        if self._is_hr_user():
            return
        for review in self:
            if review.sudo().manager_id.user_id != self.env.user:
                raise UserError(_('Only the reporting manager of %s or HR can take this decision.',
                                  review.employee_id.name))

    def _check_hr_access(self):
        if not self._is_hr_user():
            raise UserError(_('Only HR can give the second approval.'))

    def _get_hr_user(self):
        """HR Responsible set on the employee's current contract version."""
        self.ensure_one()
        return self.sudo().employee_id.hr_responsible_id

    def _start_manager_review(self):
        template = self.env.ref('bxi_employee_milestones.mail_template_probation_manager_review')
        for review in self:
            # Without a manager user, HR takes the manager step as well.
            user = review.sudo().manager_id.user_id or review._get_hr_user()
            if user:
                review.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=review.probation_end_date,
                    summary=_('Confirm probation of %s', review.employee_id.name),
                    user_id=user.id,
                )
            template.send_mail(review.id)

    def _request_hr_approval(self):
        template = self.env.ref('bxi_employee_milestones.mail_template_probation_hr_review')
        for review in self:
            hr_user = review._get_hr_user()
            if hr_user:
                review.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=review.probation_end_date,
                    summary=_('Approve probation confirmation of %s', review.employee_id.name),
                    user_id=hr_user.id,
                )
            template.send_mail(review.id)

    # ============================================================
    # ACTIONS
    # ============================================================

    def action_manager_confirm(self):
        self._check_state('manager_review')
        self._check_manager_access()
        self.write({
            'state': 'hr_review',
            'manager_decision_by': self.env.uid,
            'manager_decision_on': fields.Datetime.now(),
        })
        self.activity_feedback(['mail.mail_activity_data_todo'])
        self._request_hr_approval()
        return True

    def action_hr_approve(self):
        self._check_hr_access()
        self._check_state('hr_review')
        self.write({
            'state': 'confirmed',
            'hr_decision_by': self.env.uid,
            'hr_decision_on': fields.Datetime.now(),
        })
        for review in self:
            review.employee_id.write({
                'probation_period': 'no',
                'probation_confirmation_date': review.probation_end_date,
            })
        self.activity_feedback(['mail.mail_activity_data_todo'])
        return True

    def action_refuse(self):
        self._check_state(*OPEN_STATES)
        for review in self:
            if review.state == 'manager_review':
                review._check_manager_access()
                if not review.manager_comments:
                    raise UserError(_('Add the manager comments explaining why the probation is not confirmed.'))
                by_manager = True
                vals = {'manager_decision_by': self.env.uid, 'manager_decision_on': fields.Datetime.now()}
            else:
                review._check_hr_access()
                if not review.hr_comments:
                    raise UserError(_('Add the HR comments explaining why the probation is not confirmed.'))
                by_manager = False
                vals = {'hr_decision_by': self.env.uid, 'hr_decision_on': fields.Datetime.now()}
            review.write(dict(vals, state='refused'))
            review.activity_feedback(['mail.mail_activity_data_todo'])
            hr_user = review._get_hr_user()
            if by_manager and hr_user:
                review.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Probation of %s not confirmed by the manager: '
                              'extend the probation end date or take action',
                              review.employee_id.name),
                    user_id=hr_user.id,
                )
        return True

    def action_send_back_to_manager(self):
        self._check_hr_access()
        self._check_state('hr_review', 'refused')
        self.activity_unlink(['mail.mail_activity_data_todo'])
        self.write({
            'state': 'manager_review',
            'manager_decision_by': False,
            'manager_decision_on': False,
            'hr_decision_by': False,
            'hr_decision_on': False,
        })
        self._start_manager_review()
        return True
