# -*- coding: utf-8 -*-
from datetime import date

from freezegun import freeze_time

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


HR_EMAIL = 'hr.milestones@example.com'


@tagged('post_install', '-at_install')
class TestEmployeeMilestones(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.milestone_hr_email = HR_EMAIL
        cls.company.resource_calendar_id.tz = 'Asia/Kolkata'

        cls.manager_user = new_test_user(cls.env, login='ms_manager', groups='base.group_user')
        cls.hr_user = new_test_user(cls.env, login='ms_hr', groups='base.group_user,hr.group_hr_user')
        cls.other_user = new_test_user(cls.env, login='ms_other', groups='base.group_user')

        Employee = cls.env['hr.employee']
        cls.manager = Employee.create({
            'name': 'Milestone Manager',
            'work_email': 'manager@example.com',
            'user_id': cls.manager_user.id,
        })
        cls.employee = Employee.create({
            'name': 'Milestone Employee',
            'work_email': 'employee@example.com',
            'parent_id': cls.manager.id,
            'birthday': date(1990, 10, 21),
            'emp_date_of_joining': date(2023, 10, 21),
        })
        cls.employee.hr_responsible_id = cls.hr_user
        cls.other = Employee.create({
            'name': 'Milestone Other',
            'work_email': 'other@example.com',
            'user_id': cls.other_user.id,
        })

    def _mails(self, template_xmlid, records):
        template = self.env.ref(template_xmlid)
        return self.env['mail.mail'].search([
            ('model', '=', records._name),
            ('res_id', 'in', records.ids),
            ('subject', '=like', template.subject.split('{{')[0] + '%'),
        ])

    # ------------------------------------------------------------
    # Birthday
    # ------------------------------------------------------------

    @freeze_time('2026-10-21 04:00:00')
    def test_birthday_wish_to_employee_copying_manager(self):
        self.env['hr.employee']._cron_send_birthday_wishes()
        mails = self._mails('bxi_employee_milestones.mail_template_birthday_wish', self.employee)
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails.email_to, 'employee@example.com')
        self.assertIn('manager@example.com', mails.email_cc)
        self.assertNotIn(HR_EMAIL, mails.email_cc or '')

        # A second run on the same day does not send it again.
        self.env['hr.employee']._cron_send_birthday_wishes()
        mails = self._mails('bxi_employee_milestones.mail_template_birthday_wish', self.employee)
        self.assertEqual(len(mails), 1)

    @freeze_time('2026-10-22 04:00:00')
    def test_no_birthday_wish_on_other_days(self):
        self.env['hr.employee']._cron_send_birthday_wishes()
        self.assertFalse(self._mails('bxi_employee_milestones.mail_template_birthday_wish', self.employee))

    def test_birthday_on_29_february(self):
        self.employee.birthday = date(2000, 2, 29)
        template = 'bxi_employee_milestones.mail_template_birthday_wish'
        with freeze_time('2028-02-28 04:00:00'):  # leap year: wait for the 29th
            self.env['hr.employee']._cron_send_birthday_wishes()
        self.assertFalse(self._mails(template, self.employee))
        with freeze_time('2027-02-28 04:00:00'):
            self.env['hr.employee']._cron_send_birthday_wishes()
        self.assertEqual(len(self._mails(template, self.employee)), 1)

    # ------------------------------------------------------------
    # Job anniversary
    # ------------------------------------------------------------

    @freeze_time('2026-10-21 04:00:00')
    def test_anniversary_wish_copying_manager_and_hr(self):
        self.env['hr.employee']._cron_send_anniversary_wishes()
        mails = self._mails('bxi_employee_milestones.mail_template_job_anniversary', self.employee)
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails.email_to, 'employee@example.com')
        self.assertIn('manager@example.com', mails.email_cc)
        self.assertIn(HR_EMAIL, mails.email_cc)
        self.assertIn('3 years', mails.body_html)

        self.env['hr.employee']._cron_send_anniversary_wishes()
        mails = self._mails('bxi_employee_milestones.mail_template_job_anniversary', self.employee)
        self.assertEqual(len(mails), 1)

    @freeze_time('2026-10-21 04:00:00')
    def test_no_anniversary_wish_on_joining_day(self):
        self.employee.emp_date_of_joining = date(2026, 10, 21)
        self.env['hr.employee']._cron_send_anniversary_wishes()
        self.assertFalse(self._mails('bxi_employee_milestones.mail_template_job_anniversary', self.employee))

    # ------------------------------------------------------------
    # Probation
    # ------------------------------------------------------------

    def _start_probation(self, joining_date):
        self.employee.write({'probation_period': 'yes', 'emp_date_of_joining': joining_date})
        return self.env['hr.probation.review']._cron_start_probation_reviews()

    def test_probation_end_date_is_six_months_after_joining(self):
        self.employee.emp_date_of_joining = date(2026, 4, 30)
        self.assertEqual(self.employee.probation_end_date, date(2026, 10, 30))

    @freeze_time('2026-10-20 04:00:00')
    def test_probation_review_starts_10_days_before_end(self):
        # Ends 31 October 2026: 11 days away, too early.
        self.employee.probation_period = 'yes'
        self.employee.probation_end_date = date(2026, 10, 31)
        self.assertFalse(self.env['hr.probation.review']._cron_start_probation_reviews())

        # Joined 30 April 2026, ends 30 October 2026: 10 days away.
        review = self._start_probation(date(2026, 4, 30))
        self.assertEqual(len(review), 1)
        self.assertEqual(review.state, 'manager_review')
        self.assertEqual(review.probation_end_date, date(2026, 10, 30))
        self.assertEqual(review.activity_ids.user_id, self.manager_user)
        mail = self._mails('bxi_employee_milestones.mail_template_probation_manager_review', review)
        self.assertEqual(mail.email_to, 'manager@example.com')

        # No duplicate on the next run.
        self.assertFalse(self.env['hr.probation.review']._cron_start_probation_reviews())

    @freeze_time('2026-10-21 04:00:00')
    def test_no_probation_review_when_not_on_probation(self):
        self.employee.write({'probation_period': 'no', 'emp_date_of_joining': date(2026, 4, 30)})
        self.assertFalse(self.env['hr.probation.review']._cron_start_probation_reviews())

    @freeze_time('2026-10-21 04:00:00')
    def test_probation_manager_then_hr_confirmation(self):
        review = self._start_probation(date(2026, 4, 30))

        with self.assertRaises(AccessError):
            review.with_user(self.other_user).action_manager_confirm()
        with self.assertRaises(UserError):
            review.with_user(self.manager_user).action_hr_approve()

        review.with_user(self.manager_user).action_manager_confirm()
        self.assertEqual(review.state, 'hr_review')
        self.assertEqual(review.manager_decision_by, self.manager_user)
        self.assertEqual(review.activity_ids.user_id, self.hr_user)
        mail = self._mails('bxi_employee_milestones.mail_template_probation_hr_review', review)
        self.assertEqual(mail.email_to, HR_EMAIL)

        with self.assertRaises(UserError):
            review.with_user(self.manager_user).action_hr_approve()

        review.with_user(self.hr_user).action_hr_approve()
        self.assertEqual(review.state, 'confirmed')
        self.assertEqual(review.hr_decision_by, self.hr_user)
        self.assertFalse(review.activity_ids)
        self.assertEqual(self.employee.probation_period, 'no')
        self.assertEqual(self.employee.probation_confirmation_date, date(2026, 10, 30))

    @freeze_time('2026-10-21 04:00:00')
    def test_probation_not_confirmed_then_extended(self):
        review = self._start_probation(date(2026, 4, 30))

        with self.assertRaises(UserError):
            review.with_user(self.manager_user).action_refuse()
        review.with_user(self.manager_user).manager_comments = 'Needs more time on the project.'
        review.with_user(self.manager_user).action_refuse()
        self.assertEqual(review.state, 'refused')
        self.assertEqual(self.employee.probation_period, 'yes')
        self.assertEqual(review.activity_ids.user_id, self.hr_user)

        # Same end date: no new review.
        self.assertFalse(self.env['hr.probation.review']._cron_start_probation_reviews())

        # HR extends the probation: a new review starts 10 days before the new date.
        self.employee.probation_end_date = date(2026, 12, 31)
        self.assertFalse(self.env['hr.probation.review']._cron_start_probation_reviews())
        with freeze_time('2026-12-21 04:00:00'):
            new_review = self.env['hr.probation.review']._cron_start_probation_reviews()
        self.assertEqual(new_review.probation_end_date, date(2026, 12, 31))
        self.assertEqual(new_review.state, 'manager_review')
