from dateutil.relativedelta import relativedelta

from odoo.tests import tagged

from .common import TrainingCommon


@tagged('post_install', '-at_install')
class TestResignation(TrainingCommon):

    def _in_service(self, fee=40000, lodging=20000, end=None, **vals):
        training = self._ready(self._new_training(fee=fee, lodging=lodging, **vals))
        self._complete(training, end_date=end or self.today - relativedelta(days=10))
        return training

    def test_resignation_cancels_training_not_started(self):
        training = self._nominate(self._new_training())
        self._resign(self.employee, self.today + relativedelta(days=60))
        self.assertEqual(training.state, 'cancelled')
        self.assertIn('Resignation', training.cancel_reason)
        self.assertFalse(training.recovery_ids)

    def test_resignation_after_advance_recovers_it(self):
        training = self._ready(self._new_training(fee=10000, lodging=6000))
        self._pay_advance(training, create_entry=False)
        self._resign(self.employee, self.today + relativedelta(days=60))
        self.assertEqual(training.state, 'cancelled')
        self.assertEqual(training.recovery_ids.amount_due, 6000)

    def test_training_in_progress_is_flagged_to_hr(self):
        training = self._ready(self._new_training())
        training.with_user(self.hr_user).action_start()
        self._resign(self.employee, self.today + relativedelta(days=60))
        self.assertEqual(training.state, 'in_training')
        self.assertTrue(training.activity_ids.filtered(lambda act: 'Resignation' in (act.summary or '')))

    def test_leaving_before_end_owes_full_cost(self):
        training = self._in_service()
        agreement = training.agreement_id
        # Eleven months into a twelve-month agreement: still the full amount, no pro-rata.
        last_day = agreement.end_date - relativedelta(months=1)
        resignation = self._resign(self.employee, last_day, approve=True)
        self.assertEqual(agreement.state, 'breached')
        self.assertEqual(agreement.breach_date, last_day)
        recovery = agreement.recovery_ids
        self.assertEqual(recovery.reason, 'breach')
        self.assertEqual(recovery.amount_due, 60000)
        self.assertEqual(recovery.state, 'payroll')
        self.assertEqual(recovery.payroll_month, last_day.replace(day=1))
        self.assertEqual(recovery.resignation_id, resignation)
        self.assertEqual(resignation.trn_due_amount, 60000)

    def test_leaving_after_end_owes_nothing(self):
        training = self._in_service()
        agreement = training.agreement_id
        self._resign(self.employee, agreement.end_date + relativedelta(days=1), approve=True)
        self.assertEqual(agreement.state, 'in_service')
        self.assertFalse(agreement.recovery_ids)

    def test_each_agreement_recovered_separately(self):
        first = self._in_service(fee=40000, lodging=20000)
        second = self._in_service(fee=90000, lodging=20000, start_in=40)
        self._resign(self.employee, self.today + relativedelta(days=30), approve=True)
        recoveries = (first | second).recovery_ids
        self.assertEqual(len(recoveries), 2)
        self.assertEqual(sorted(recoveries.mapped('amount_due')), [60000, 110000])

    def test_offboarding_shows_training_dues(self):
        training = self._in_service()
        offboarding = self.env['employee.onboarding.offboarding'].new({
            'offboarding_employee_id': self.employee.id,
            'effective_date': self.today + relativedelta(days=30),
        })
        self.assertEqual(offboarding.training_agreement_ids.ids, training.agreement_id.ids)
        self.assertEqual(offboarding.training_due_amount, 60000)

    def test_payment_and_waiver(self):
        training = self._in_service()
        self._resign(self.employee, self.today + relativedelta(days=30), approve=True)
        recovery = training.agreement_id.recovery_ids
        wizard = self.env['bxi.training.recovery.payment.wizard'].with_user(self.hr_user).create({
            'recovery_id': recovery.id})
        wizard.amount = 50000
        wizard.action_confirm()
        self.assertEqual(recovery.balance, 10000)
        self.assertEqual(recovery.state, 'payroll')
        admin = self.env.ref('base.user_admin')
        self.env['bxi.training.recovery.waive.wizard'].with_user(admin).create({
            'recovery_id': recovery.id, 'reason': 'Management decision'}).action_confirm()
        self.assertEqual(recovery.state, 'waived')
        self.assertEqual(training.agreement_id.state, 'waived')

    def test_full_repayment_closes_agreement(self):
        training = self._in_service()
        self._resign(self.employee, self.today + relativedelta(days=30), approve=True)
        recovery = training.agreement_id.recovery_ids
        self.env['bxi.training.recovery.payment.wizard'].with_user(self.finance_user).create({
            'recovery_id': recovery.id}).action_confirm()
        self.assertEqual(recovery.state, 'recovered')
        self.assertEqual(training.agreement_id.state, 'recovered')
