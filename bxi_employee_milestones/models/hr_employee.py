# -*- coding: utf-8 -*-
import calendar
import logging

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


_logger = logging.getLogger(__name__)

PROBATION_MONTHS = 6


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    probation_end_date = fields.Date(
        string='Probation End Date',
        compute='_compute_probation_end_date', store=True, readonly=False,
        groups='hr.group_hr_user', tracking=True,
        help='Date of joining + 6 months. Move it to extend the probation: '
             'a new review starts 10 days before the new date.',
    )
    probation_confirmation_date = fields.Date(
        string='Confirmation Date', readonly=True, copy=False,
        groups='hr.group_hr_user', tracking=True,
    )
    probation_review_ids = fields.One2many(
        'hr.probation.review', 'employee_id', string='Probation Reviews',
        groups='hr.group_hr_user',
    )
    probation_review_count = fields.Integer(
        compute='_compute_probation_review_count', groups='hr.group_hr_user')
    # Year of the last email sent, so a rerun of the job on the same day does not resend it.
    birthday_wish_year = fields.Integer(copy=False, groups='hr.group_hr_user')
    anniversary_wish_year = fields.Integer(copy=False, groups='hr.group_hr_user')

    @api.depends('emp_date_of_joining')
    def _compute_probation_end_date(self):
        for employee in self:
            employee.probation_end_date = (
                employee.emp_date_of_joining + relativedelta(months=PROBATION_MONTHS)
                if employee.emp_date_of_joining else False
            )

    def _compute_probation_review_count(self):
        counts = dict(self.env['hr.probation.review']._read_group(
            [('employee_id', 'in', self.ids)], ['employee_id'], ['__count']))
        for employee in self:
            employee.probation_review_count = counts.get(employee, 0)

    def action_view_probation_reviews(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'bxi_employee_milestones.action_hr_probation_review')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {}
        return action

    # ============================================================
    # SCHEDULED JOBS
    # ============================================================

    @api.model
    def _milestone_today(self):
        """Today in the timezone of the company working schedule, not of
        the user running the cron, so the date does not shift."""
        tz = self.env.company.resource_calendar_id.tz or 'Asia/Kolkata'
        return fields.Date.context_today(self.with_context(tz=tz))

    @api.model
    def _milestone_domain(self, date_field, today):
        """Employees whose ``date_field`` falls on today's day and month.
        A 29 February date is celebrated on 28 February in other years."""
        days = [today.day]
        if (today.month, today.day) == (2, 28) and not calendar.isleap(today.year):
            days.append(29)
        return [
            (f'{date_field}.month_number', '=', today.month),
            (f'{date_field}.day_of_month', 'in', days),
            ('work_email', '!=', False),
        ]

    @api.model
    def _cron_send_birthday_wishes(self):
        today = self._milestone_today()
        employees = self.sudo().search(self._milestone_domain('birthday', today) + [
            ('birthday_wish_year', '!=', today.year),
        ])
        template = self.env.ref('bxi_employee_milestones.mail_template_birthday_wish')
        for employee in employees:
            template.send_mail(employee.id)
        employees.write({'birthday_wish_year': today.year})
        _logger.info('Birthday wishes queued for %s employee(s)', len(employees))

    @api.model
    def _cron_send_anniversary_wishes(self):
        today = self._milestone_today()
        employees = self.sudo().search(self._milestone_domain('emp_date_of_joining', today) + [
            ('emp_date_of_joining.year_number', '<', today.year),
            ('anniversary_wish_year', '!=', today.year),
        ])
        template = self.env.ref('bxi_employee_milestones.mail_template_job_anniversary')
        for employee in employees:
            years = today.year - employee.emp_date_of_joining.year
            template.with_context(anniversary_years=years).send_mail(employee.id)
        employees.write({'anniversary_wish_year': today.year})
        _logger.info('Job anniversary wishes queued for %s employee(s)', len(employees))
