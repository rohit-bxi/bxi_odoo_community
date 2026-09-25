from datetime import timedelta

from odoo.tests import tagged

from .common import CertificationCommon


@tagged('post_install', '-at_install')
class TestResignationOffboarding(CertificationCommon):

    # ── Resignation ──────────────────────────────────────────────────────
    def test_resignation_refuses_every_open_request(self):
        draft = self._new_request()
        pending = self._new_request()
        pending.action_submit()
        claimed = self._claim(self._pre_approve(self._new_request()), [1000])
        at_finance = self._full_claim([1000])
        self._resign(self.engineer)
        for request in (draft, pending, claimed, at_finance):
            self.assertEqual(request.state, 'refused')
            self.assertIn('resignation', request.refuse_reason)
        self.assertEqual(set((claimed | at_finance).expense_ids.mapped('state')), {'refused'})

    def test_resignation_created_as_submitted(self):
        request = self._claim(self._pre_approve(self._new_request()), [1000])
        self.env['employee.resignation'].create({
            'employee_id': self.engineer.id, 'last_working_day': self.today + timedelta(days=30),
            'reason': 'personal', 'resignation_body': '<p>x</p>', 'state': 'submitted',
        })
        self.assertEqual(request.state, 'refused')

    def test_draft_resignation_does_not_refuse(self):
        request = self._claim(self._pre_approve(self._new_request()), [1000])
        self._resign(self.engineer, submit=False)
        self.assertEqual(request.state, 'claim_approval')

    def test_reimbursed_claim_is_kept(self):
        request = self._full_claim([1000])
        request.expense_ids.action_finance_approved()
        self._resign(self.engineer)
        self.assertEqual(request.state, 'reimbursed')

    def test_other_employees_are_not_affected(self):
        request = self._claim(self._pre_approve(self._new_request()), [1000])
        self._resign(self.manager)
        self.assertEqual(request.state, 'claim_approval')

    def test_pending_agreement_is_cancelled(self):
        request = self._full_claim([8000])
        self._resign(self.engineer)
        self.assertEqual(request.state, 'refused')
        self.assertEqual(request.service_agreement_id.state, 'cancelled')

    # ── Offboarding dues ─────────────────────────────────────────────────
    def _offboarding(self, employee, effective_date):
        request_type = self.env['boarding.request.type'].create({'name': 'Offboarding'})
        return self.env['employee.onboarding.offboarding'].create({
            'request_type_id': request_type.id,
            'offboarding_employee_id': employee.id,
            'effective_date': effective_date,
        })

    def test_offboarding_shows_agreements_and_vouchers(self):
        active = self._create_agreement(amount=9000, start_date=self.today - timedelta(days=30), state='active')
        self._create_agreement(amount=5000, state='recovered')
        voucher = self.env['bxi.certification.voucher'].create({
            'employee_id': self.engineer.id, 'certification_id': self.certification.id, 'cost': 3000,
            'issue_date': self.today - timedelta(days=60), 'deadline': self.today - timedelta(days=1),
            'state': 'expired',
        })
        offboarding = self._offboarding(self.engineer, self.today + timedelta(days=30))
        self.assertEqual(offboarding.certification_agreement_ids, active)
        self.assertEqual(offboarding.certification_voucher_ids, voucher)
        self.assertEqual(offboarding.certification_due_amount, 12000)
        self.assertEqual(offboarding.certification_currency_id, self.env.company.currency_id)

    def test_agreement_served_before_leaving_is_not_due(self):
        self._create_agreement(start_date=self.today - timedelta(days=150), period_months=6, state='active')
        offboarding = self._offboarding(self.engineer, self.today + timedelta(days=60))
        self.assertFalse(offboarding.certification_agreement_ids)
        self.assertEqual(offboarding.certification_due_amount, 0)

    def test_offboarding_without_employee(self):
        request_type = self.env['boarding.request.type'].create({'name': 'Onboarding'})
        onboarding = self.env['employee.onboarding.offboarding'].create({'request_type_id': request_type.id})
        self.assertFalse(onboarding.certification_agreement_ids)
        self.assertEqual(onboarding.certification_due_amount, 0)
