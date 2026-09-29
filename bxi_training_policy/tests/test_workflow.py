import base64

from dateutil.relativedelta import relativedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import TrainingCommon, make_pdf


@tagged('post_install', '-at_install')
class TestTrainingWorkflow(TrainingCommon):

    # ── Documents before the training ────────────────────────────────────
    def test_no_agreement_below_threshold(self):
        training = self._nominate(self._new_training(fee=15000, lodging=5000))
        training._on_form_signed()
        self.assertEqual(training.form_signed_date, self.today)
        self.assertEqual(training.state, 'ready')
        self.assertFalse(training.agreement_id)

    def test_agreement_issued_after_form(self):
        training = self._nominate(self._new_training(fee=40000, lodging=20000))
        training._on_form_signed()
        agreement = training.agreement_id
        self.assertEqual(training.state, 'agreement_pending')
        self.assertEqual(agreement.state, 'issued')
        self.assertEqual(agreement.amount, 60000)
        self.assertEqual(agreement.period_months, 12)
        self.assertFalse(agreement.start_date)
        self.assertTrue(agreement.template_attachment_id)
        self.assertEqual(agreement.execution_mode, 'stamp_paper')

    def test_two_year_agreement_from_one_lakh(self):
        training = self._nominate(self._new_training(fee=90000, lodging=15000))
        training._on_form_signed()
        self.assertEqual(training.agreement_id.period_months, 24)

    def test_execution_details_required(self):
        training = self._nominate(self._new_training())
        training._on_form_signed()
        agreement = training.agreement_id.with_user(self.employee.user_id)
        with self.assertRaisesRegex(UserError, 'stamp paper number'):
            agreement.action_submit_execution()
        scan = self.env['ir.attachment'].with_user(self.employee.user_id).create({
            'name': 'scan.pdf', 'raw': make_pdf()})
        agreement.write({
            'stamp_paper_no': 'X1', 'stamp_paper_value': 50, 'stamp_paper_date': self.today,
            'witness1_name': 'A', 'witness2_name': 'B', 'notary_name': 'N', 'notarised_date': self.today,
            'executed_scan_ids': [(6, 0, scan.ids)],
        })
        with self.assertRaisesRegex(UserError, 'stamp paper worth'):
            agreement.action_submit_execution()
        agreement.stamp_paper_value = 100
        agreement.action_submit_execution()
        self.assertEqual(agreement.state, 'submitted')
        # The employee cannot change the terms, nor the details once submitted.
        with self.assertRaises(UserError):
            agreement.write({'witness1_name': 'Someone else'})
        with self.assertRaises(AccessError):
            training.agreement_id.with_user(self.employee.user_id).write({'amount': 1})

    def test_hr_checklist_and_send_back(self):
        training = self._nominate(self._new_training())
        training._on_form_signed()
        agreement = self._execute_agreement(training)
        self.assertEqual(agreement.state, 'executed')
        self.assertEqual(agreement.verified_by_id, self.hr_user)
        self.assertEqual(training.state, 'ready')

        other = self._nominate(self._new_training())
        other._on_form_signed()
        other_agreement = other.agreement_id
        other_agreement.with_user(self.employee.user_id).write({
            'stamp_paper_no': 'X2', 'stamp_paper_date': self.today, 'witness1_name': 'A', 'witness2_name': 'B',
            'notary_name': 'N', 'notarised_date': self.today,
            'executed_scan_ids': [(0, 0, {'name': 'scan.pdf', 'raw': make_pdf()})],
        })
        other_agreement.with_user(self.employee.user_id).action_submit_execution()
        wizard = self.env['bxi.training.agreement.verify.wizard'].with_user(self.hr_user).create({
            'agreement_id': other_agreement.id, 'check_stamp_paper': True})
        with self.assertRaisesRegex(UserError, 'Tick every check'):
            wizard.action_verify()
        wizard.send_back_reason = 'Notary seal missing on page 3'
        wizard.action_send_back()
        self.assertEqual(other_agreement.state, 'issued')
        self.assertEqual(other.state, 'agreement_pending')

    def test_training_cannot_start_without_documents(self):
        training = self._nominate(self._new_training())
        training._on_form_signed()
        training.sudo().state = 'ready'  # forced: the agreement is not executed
        with self.assertRaisesRegex(UserError, 'service agreement'):
            training.with_user(self.hr_user).action_start()
        with self.assertRaisesRegex(UserError, 'service agreement'):
            self._pay_advance(training)

    def test_policy_acknowledgement_required_before_start(self):
        policy = self.env['hr.company.policy'].create({'name': 'Training Policy', 'scope': 'all'})
        version = self.env['hr.company.policy.version'].create({
            'policy_id': policy.id,
            'document': base64.b64encode(make_pdf('Training Policy')),
            'filename': 'training_policy.pdf',
        })
        version.sudo().state = 'published'
        self.company.trn_policy_id = policy
        training = self._ready(self._new_training(fee=10000, lodging=5000))
        status = self.employee._trn_get_policy_status()
        self.assertTrue(status['ack'])  # requested when HR confirmed the nomination
        self.assertTrue(status['required'])
        with self.assertRaisesRegex(UserError, 'Training Policy'):
            training.with_user(self.hr_user).action_start()
        status['ack'].sudo().state = 'acknowledged'
        training.with_user(self.hr_user).action_start()
        self.assertEqual(training.state, 'in_training')

    # ── Advance, training and claim ──────────────────────────────────────
    def test_full_flow_with_agreement(self):
        self._setup_accounting()
        training = self._ready(self._new_training(fee=40000, lodging=20000))
        agreement = training.agreement_id

        self._pay_advance(training)
        self.assertEqual(training.advance_amount, 20000)  # employee-paid estimate
        move = training.advance_move_id
        self.assertEqual(move.state, 'posted')
        debit = move.line_ids.filtered('debit')
        self.assertEqual(debit.account_id, self.advance_account)
        self.assertEqual(debit.partner_id, self.employee.work_contact_id)

        end = self.today - relativedelta(days=1)
        self._complete(training, end_date=end)
        self.assertEqual(training.state, 'completed')
        self.assertEqual(agreement.state, 'in_service')
        self.assertEqual(agreement.start_date, end)
        self.assertEqual(agreement.end_date, end + relativedelta(months=12))
        self.assertEqual(training.claim_due_date, end + relativedelta(days=30))

        # The company paid the provider 40,000; the employee spent 18,000 on lodging.
        training.cost_line_ids.filtered(lambda line: line.paid_by == 'company').with_user(self.hr_user).actual_amount = 40000
        self._add_claim_line(training, self.lodging_product, 18000)
        training.with_user(self.employee.user_id).action_submit_claim()
        self.assertEqual(training.state, 'claim_approval')
        self.assertEqual(training.approval_line_ids.mapped('role'), ['rm', 'hr', 'es'])
        self.assertEqual(training.expense_ids.state, 'training_approval')
        self.assertEqual(training.expense_ids.account_id, self.bonded_account)
        self.assertEqual(training.consolidated_cost, 58000)

        # Approvals run in order.
        self.assertFalse(training.with_user(self.hr_user).can_approve)
        with self.assertRaises(UserError):
            training.with_user(self.hr_user).action_approve_claim()
        self._approve_claim(training)
        self.assertEqual(training.state, 'finance_approval')
        self.assertEqual(training.expense_ids.state, 'finance_approval')

        training.expense_ids.with_user(self.finance_user).action_finance_approved()
        self.assertEqual(training.state, 'settled')
        # The 20,000 advance covers the 18,000 claim; 2,000 comes back through payroll.
        settlement = training.settlement_move_id
        self.assertEqual(settlement.line_ids.filtered('credit').account_id, self.advance_account)
        self.assertEqual(sum(settlement.line_ids.mapped('debit')), 18000)
        recovery = training.recovery_ids
        self.assertEqual(recovery.reason, 'advance_excess')
        self.assertEqual(recovery.amount_due, 2000)
        self.assertEqual(recovery.state, 'payroll')
        # The agreement now carries the actual cost; same tier, no addendum.
        self.assertEqual(agreement.amount, 58000)
        self.assertFalse(agreement.addendum_ids)

    def test_higher_actual_cost_needs_addendum(self):
        training = self._ready(self._new_training(fee=40000, lodging=20000))
        self._pay_advance(training, create_entry=False)
        self._complete(training)
        training.cost_line_ids.filtered(lambda line: line.paid_by == 'company').with_user(self.hr_user).actual_amount = 80000
        self._add_claim_line(training, self.lodging_product, 25000)
        training.with_user(self.employee.user_id).action_submit_claim()
        self._approve_claim(training)
        training.expense_ids.with_user(self.finance_user).action_finance_approved()
        old = training.agreement_id
        addendum = old.addendum_ids
        self.assertEqual(addendum.state, 'issued')
        self.assertEqual(addendum.period_months, 24)
        self.assertEqual(addendum.amount, 105000)
        self._execute_agreement_record(addendum)
        self.assertEqual(old.state, 'superseded')
        self.assertEqual(addendum.state, 'in_service')
        self.assertEqual(addendum.start_date, old.start_date)
        self.assertEqual(training.agreement_id, addendum)

    def _execute_agreement_record(self, agreement):
        agreement.with_user(self.employee.user_id).write({
            'stamp_paper_no': 'ADD-1', 'stamp_paper_date': self.today, 'witness1_name': 'A',
            'witness2_name': 'B', 'notary_name': 'N', 'notarised_date': self.today,
            'executed_scan_ids': [(0, 0, {'name': 'addendum.pdf', 'raw': make_pdf()})],
        })
        agreement.with_user(self.employee.user_id).action_submit_execution()
        self.env['bxi.training.agreement.verify.wizard'].with_user(self.hr_user).create({
            'agreement_id': agreement.id, 'check_stamp_paper': True, 'check_employee_signature': True,
            'check_witnesses': True, 'check_notary': True, 'check_terms': True,
        }).action_verify()

    def test_actual_cost_crossing_threshold_requires_agreement(self):
        training = self._ready(self._new_training(fee=15000, lodging=5000))
        self.assertFalse(training.agreement_id)
        self._complete(training)
        training.cost_line_ids.filtered(lambda line: line.paid_by == 'company').with_user(self.hr_user).actual_amount = 25000
        self._add_claim_line(training, self.lodging_product, 9000)
        training.with_user(self.employee.user_id).action_submit_claim()
        self._approve_claim(training)
        training.expense_ids.with_user(self.finance_user).action_finance_approved()
        agreement = training.agreement_id
        self.assertEqual(agreement.state, 'issued')
        self.assertEqual(agreement.amount, 34000)
        self._execute_agreement_record(agreement)
        self.assertEqual(agreement.state, 'in_service')
        self.assertEqual(agreement.start_date, training.actual_end_date)

    def test_claim_rules(self):
        training = self._ready(self._new_training(fee=10000, lodging=5000))
        self._complete(training)
        with self.assertRaisesRegex(UserError, 'claim lines'):
            training.with_user(self.employee.user_id).action_submit_claim()
        # Only "Specialized Training" categories.
        misc = self.env['product.product'].create({'name': 'Miscellaneous', 'can_be_expensed': True})
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self.env['hr.expense'].with_user(self.employee.user_id).create({
                'name': 'Hotel', 'product_id': misc.id, 'total_amount_currency': 3000,
                'employee_id': self.employee.id, 'training_request_id': training.id,
            })
        expense = self.env['hr.expense'].with_user(self.employee.user_id).create({
            'name': 'Hotel', 'product_id': self.lodging_product.id, 'total_amount_currency': 3000,
            'employee_id': self.employee.id, 'training_request_id': training.id,
        })
        with self.assertRaisesRegex(UserError, 'receipt'):
            training.with_user(self.employee.user_id).action_submit_claim()
        self.env['ir.attachment'].create({
            'name': 'receipt.pdf', 'raw': make_pdf(), 'res_model': 'hr.expense', 'res_id': expense.id})
        training.with_user(self.employee.user_id).action_submit_claim()
        with self.assertRaisesRegex(UserError, 'cannot be modified'):
            expense.with_user(self.employee.user_id).write({'total_amount_currency': 9000})

    def test_refer_back_and_resubmit(self):
        training = self._ready(self._new_training(fee=10000, lodging=5000))
        self._complete(training)
        self._add_claim_line(training, self.lodging_product, 4000)
        training.with_user(self.employee.user_id).action_submit_claim()
        training.with_user(self.manager.user_id).action_approve_claim()
        wizard = self.env['bxi.training.refuse.wizard'].with_user(self.hr_user).create({
            'request_id': training.id, 'reason': 'Hotel bill missing GST number'})
        self.assertTrue(wizard.is_claim)
        wizard.action_confirm()
        self.assertEqual(training.state, 'completed')
        self.assertEqual(training.expense_ids.state, 'draft')
        self.assertIn('GST', training.refuse_reason)
        training.with_user(self.employee.user_id).action_submit_claim()
        self.assertEqual(training.state, 'claim_approval')
        self.assertEqual(len(training.approval_line_ids), 3)
        self.assertTrue(all(line.state == 'pending' for line in training.approval_line_ids))

    def test_responsible_users_approve_and_duplicates_skipped(self):
        self.company.trn_hr_user_id = self.manager.user_id
        self.company.trn_es_user_id = self.es_user
        training = self._ready(self._new_training(fee=10000, lodging=5000))
        self._complete(training)
        self._add_claim_line(training, self.lodging_product, 4000)
        training.with_user(self.employee.user_id).action_submit_claim()
        # The Reporting Manager is also the HR responsible: one approval only.
        self.assertEqual(training.approval_line_ids.mapped('role'), ['rm', 'es'])
        training.with_user(self.manager.user_id).action_approve_claim()
        self.assertFalse(training.with_user(self.hr_user).can_approve)
        training.with_user(self.es_user).action_approve_claim()
        self.assertEqual(training.state, 'finance_approval')

    def test_settle_without_claim(self):
        training = self._ready(self._new_training(fee=40000, lodging=0))
        self._complete(training)
        training.cost_line_ids.filtered(lambda line: line.paid_by == 'company').with_user(self.hr_user).actual_amount = 38000
        training.with_user(self.es_user).action_settle_without_claim()
        self.assertEqual(training.state, 'settled')
        self.assertEqual(training.agreement_id.amount, 38000)

    def test_cancel_after_advance_recovers_it(self):
        training = self._ready(self._new_training(fee=10000, lodging=5000))
        self._pay_advance(training, create_entry=False)
        wizard = self.env['bxi.training.cancel.wizard'].with_user(self.hr_user).create({
            'request_id': training.id, 'reason': 'Program cancelled by the provider'})
        wizard.action_confirm()
        self.assertEqual(training.state, 'cancelled')
        self.assertEqual(training.recovery_ids.reason, 'cancelled')
        self.assertEqual(training.recovery_ids.amount_due, 5000)

    def test_one_agreement_per_training(self):
        first = self._ready(self._new_training(fee=40000, lodging=20000))
        second = self._ready(self._new_training(fee=90000, lodging=20000, start_in=90))
        self.assertNotEqual(first.agreement_id, second.agreement_id)
        self.assertEqual((first.agreement_id | second.agreement_id).mapped('period_months'), [12, 24])
        self.assertEqual(self.employee.trn_request_count, 2)

    # ── Cost changes before the agreement is executed ────────────────────
    def test_raised_estimate_requires_agreement(self):
        training = self._ready(self._new_training(fee=15000, lodging=5000))
        self.assertEqual(training.state, 'ready')
        training.cost_line_ids.filtered(lambda line: line.category == 'fee').with_user(self.hr_user).estimated_amount = 45000
        self.assertEqual(training.state, 'agreement_pending')
        self.assertEqual(training.agreement_id.state, 'issued')
        self.assertEqual(training.agreement_id.amount, 50000)

    def test_issued_agreement_follows_estimate(self):
        training = self._nominate(self._new_training(fee=40000, lodging=20000))
        training._on_form_signed()
        agreement = training.agreement_id
        self.assertEqual(agreement.period_months, 12)
        training.cost_line_ids.filtered(lambda line: line.category == 'fee').with_user(self.hr_user).estimated_amount = 90000
        self.assertEqual(agreement.amount, 110000)
        self.assertEqual(agreement.period_months, 24)
        self.assertEqual(agreement.state, 'issued')
        # Below the threshold: no agreement needed any more.
        training.cost_line_ids.filtered(lambda line: line.category == 'fee').with_user(self.hr_user).estimated_amount = 5000
        self.assertEqual(agreement.state, 'cancelled')
        self.assertFalse(training.agreement_id)
        self.assertEqual(training.state, 'ready')

    def test_employee_cannot_edit_or_delete_nomination(self):
        training = self._new_training()
        with self.assertRaises(AccessError):
            training.with_user(self.employee.user_id).write({'location': 'Goa'})
        with self.assertRaises(AccessError):
            training.with_user(self.employee.user_id).unlink()
        training.with_user(self.head.user_id).write({'location': 'Goa'})
        training.with_user(self.head.user_id).unlink()
