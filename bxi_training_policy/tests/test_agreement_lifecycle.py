from dateutil.relativedelta import relativedelta

from odoo.tests import tagged

from .common import TrainingCommon


@tagged('post_install', '-at_install')
class TestAgreementLifecycle(TrainingCommon):

    def test_served_agreement_is_settled_off(self):
        self._setup_accounting()
        training = self._ready(self._new_training(fee=40000, lodging=20000))
        self._complete(training, end_date=self.today - relativedelta(days=1))
        agreement = training.agreement_id
        agreement.sudo().start_date = self.today - relativedelta(months=12, days=2)
        self.env['bxi.training.agreement']._cron_daily()
        self.assertEqual(agreement.state, 'completed')
        move = agreement.writeoff_move_id
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.line_ids.filtered('debit').account_id, self.expense_account)
        self.assertEqual(move.line_ids.filtered('credit').account_id, self.bonded_account)
        self.assertEqual(sum(move.line_ids.mapped('debit')), 60000)

    def test_expense_mode_has_no_writeoff(self):
        self._setup_accounting()
        self.company.trn_accounting_mode = 'expense'
        training = self._ready(self._new_training(fee=40000, lodging=20000))
        self._complete(training, end_date=self.today - relativedelta(days=1))
        agreement = training.agreement_id
        agreement.sudo().start_date = self.today - relativedelta(months=13)
        self.env['bxi.training.agreement']._cron_daily()
        self.assertEqual(agreement.state, 'completed')
        self.assertFalse(agreement.writeoff_move_id)

    def test_ending_soon_notifies_hr_once(self):
        training = self._ready(self._new_training())
        self._complete(training)
        agreement = training.agreement_id
        agreement.sudo().start_date = self.today - relativedelta(months=12) + relativedelta(days=10)
        self.env['bxi.training.agreement']._cron_daily()
        self.assertTrue(agreement.expiry_notified)
        count = len(agreement.activity_ids)
        self.env['bxi.training.agreement']._cron_daily()
        self.assertEqual(len(agreement.activity_ids), count)

    def test_request_cron_reminders_and_start(self):
        training = self._nominate(self._new_training(start_in=8, short_notice_reason='Urgent'))
        # Form due 7 days before: tomorrow; reminder sent.
        messages = len(training.message_ids)
        self.env['bxi.training.request']._cron_daily()
        self.assertGreater(len(training.message_ids), messages)

        ready = self._ready(self._new_training(fee=10000, lodging=5000))
        ready.sudo().write({'start_date': self.today, 'end_date': self.today + relativedelta(days=2)})
        self.env['bxi.training.request']._cron_daily()
        self.assertEqual(ready.state, 'in_training')

    def test_overdue_form_escalated(self):
        training = self._nominate(self._new_training())
        # Informed 30 days ahead, but the form was due 7 days before a training starting in 3 days.
        training.sudo().write({'hr_notified_date': self.today - relativedelta(days=27),
                               'start_date': self.today + relativedelta(days=3),
                               'end_date': self.today + relativedelta(days=5)})
        self.assertLess(training.form_due_date, self.today)
        self.env['bxi.training.request']._cron_daily()
        self.assertTrue(training.form_escalated)

    def test_esign_execution(self):
        training = self._nominate(self._new_training())
        training._on_form_signed()
        agreement = training.agreement_id
        agreement.sudo().write({'state': 'draft', 'execution_mode': 'esign'})
        agreement.with_user(self.hr_user).action_issue()
        self.assertTrue(agreement.sign_request_id)
        agreement._on_esigned()
        self.assertEqual(agreement.state, 'executed')
        self.assertEqual(training.state, 'ready')
