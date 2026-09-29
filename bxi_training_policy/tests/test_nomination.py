from dateutil.relativedelta import relativedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import TrainingCommon


@tagged('post_install', '-at_install')
class TestNomination(TrainingCommon):

    def test_department_head_nominates(self):
        training = self._new_training()
        self.assertEqual(training.nominated_by_id, self.head)
        self.assertEqual(training.estimated_cost, 60000)
        training.action_submit()
        self.assertEqual(training.state, 'hr_review')
        self.assertEqual(training.hr_notified_date, self.today)
        self.assertEqual(training.lead_days, 30)
        self.assertFalse(training.is_short_notice)
        self.assertEqual(training.manager_id, self.manager)
        self.assertTrue(training.activity_ids.filtered(lambda act: act.user_id == self.hr_user))

    def test_only_department_head_or_hr_nominates(self):
        with self.assertRaises(AccessError):
            self.env['bxi.training.request'].with_user(self.employee.user_id).create({
                'employee_id': self.employee.id, 'training_name': 'Self nomination', 'location': 'Pune',
                'purpose': 'Growth', 'start_date': self.today + relativedelta(days=30),
                'end_date': self.today + relativedelta(days=31),
            })
        # The Reporting Manager is not the Department Head.
        with self.assertRaises(AccessError):
            self.env['bxi.training.request'].with_user(self.manager.user_id).create({
                'employee_id': self.employee.id, 'training_name': 'Manager nomination', 'location': 'Pune',
                'purpose': 'Growth', 'start_date': self.today + relativedelta(days=30),
                'end_date': self.today + relativedelta(days=31),
            })
        by_hr = self.env['bxi.training.request'].with_user(self.hr_user).create({
            'employee_id': self.employee.id, 'training_name': 'HR nomination', 'location': 'Pune',
            'purpose': 'Growth', 'start_date': self.today + relativedelta(days=30),
            'end_date': self.today + relativedelta(days=31),
        })
        self.assertEqual(by_hr.state, 'draft')

    def test_short_notice_needs_reason(self):
        training = self._new_training(start_in=10)
        self.assertTrue(training.is_short_notice)
        with self.assertRaisesRegex(UserError, '20 days'):
            training.action_submit()
        training.short_notice_reason = 'Client asked for the certification this month'
        training.action_submit()
        self.assertEqual(training.state, 'hr_review')
        self.assertEqual(training.lead_days, 10)

    def test_estimated_cost_required(self):
        training = self._new_training(cost_line_ids=[])
        with self.assertRaisesRegex(UserError, 'estimated cost'):
            training.action_submit()

    def test_resigned_employee_cannot_be_nominated(self):
        self._resign(self.employee, self.today + relativedelta(days=60))
        training = self._new_training()
        with self.assertRaisesRegex(UserError, 'resignation'):
            training.action_submit()

    def test_nomination_frozen_after_submission(self):
        training = self._new_training()
        training.action_submit()
        with self.assertRaises(UserError):
            training.with_user(self.head.user_id).write({'location': 'Chennai'})
        with self.assertRaises(AccessError):
            training.with_user(self.head.user_id).write({'state': 'ready'})

    def test_form_due_date(self):
        training = self._new_training(start_in=30)
        self.assertEqual(training.form_due_date, training.start_date - relativedelta(days=7))
        short = self._new_training(start_in=5, short_notice_reason='Urgent')
        # Short notice: before the training begins.
        self.assertEqual(short.form_due_date, short.start_date - relativedelta(days=1))

    def test_confirm_sends_form_for_signature(self):
        training = self._nominate(self._new_training())
        self.assertEqual(training.state, 'form_pending')
        self.assertTrue(training.form_sign_request_id)
        self.assertEqual(training.form_sign_request_id.reference_doc, training)
        self.assertTrue(training.with_user(self.employee.user_id)._get_portal_sign_url())

    def test_employee_cannot_confirm(self):
        training = self._new_training()
        training.action_submit()
        with self.assertRaises(AccessError):
            training.with_user(self.employee.user_id).action_hr_confirm()

    def test_refuse_nomination(self):
        training = self._nominate(self._new_training())
        wizard = self.env['bxi.training.refuse.wizard'].with_user(self.hr_user).create({
            'request_id': training.id, 'reason': 'Budget freeze'})
        wizard.action_confirm()
        self.assertEqual(training.state, 'refused')
        self.assertEqual(training.form_sign_request_id.state, 'canceled')
        training.with_user(self.head.user_id).action_reset_to_draft()
        self.assertEqual(training.state, 'draft')
