from datetime import timedelta
from unittest.mock import patch

from dateutil.relativedelta import relativedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import CertificationCommon


@tagged('post_install', '-at_install')
class TestServiceAgreement(CertificationCommon):

    # ── Tiers (Annexure A) ───────────────────────────────────────────────
    def test_tiers(self):
        Tier = self.env['bxi.service.agreement.tier']
        self.assertEqual(Tier._get_months(7999.99), 0)
        self.assertEqual(Tier._get_months(8000), 6)
        self.assertEqual(Tier._get_months(19999.99), 6)
        self.assertEqual(Tier._get_months(20000), 12)
        self.assertEqual(Tier._get_months(50000), 12)
        self.assertEqual(Tier._get_months(50000.01), 18)
        self.assertEqual(Tier._get_months(1000000), 18)
        self.assertEqual(Tier._get_min_amount(), 8000)

    def test_tier_constraints(self):
        Tier = self.env['bxi.service.agreement.tier']
        with self.assertRaises(ValidationError):
            Tier.create({'min_amount': 100, 'months': 0})
        with self.assertRaises(ValidationError):
            Tier.create({'min_amount': 100, 'max_amount': 50, 'months': 3})

    def test_tiers_are_configurable(self):
        self.tier_6.min_amount = 10000
        self.assertEqual(self.env['bxi.service.agreement.tier']._get_months(9000), 0)

    # ── Agreement record ─────────────────────────────────────────────────
    def test_sequence_and_end_date(self):
        agreement = self._create_agreement(start_date=self.today, period_months=12)
        self.assertTrue(agreement.name.startswith('CERT-SA/'))
        self.assertEqual(agreement.end_date, self.today + relativedelta(months=12))
        self.assertEqual(agreement.state, 'draft')

    def test_certification_label(self):
        request = self._full_claim([8000])
        self.assertEqual(request.service_agreement_id.certification_label, self.certification.display_name)

    def test_is_due_on(self):
        agreement = self._create_agreement(start_date=self.today, period_months=6, state='active')
        self.assertTrue(agreement._is_due_on(self.today + timedelta(days=30)))
        self.assertFalse(agreement._is_due_on(self.today + relativedelta(months=7)))
        self.assertTrue(agreement._is_due_on(False))
        agreement.state = 'completed'
        self.assertFalse(agreement._is_due_on(self.today))

    # ── Claim flow ───────────────────────────────────────────────────────
    def test_no_agreement_below_8000(self):
        request = self._full_claim([7999])
        self.assertFalse(request.service_agreement_id)
        self.assertEqual(request.state, 'finance_approval')

    def test_agreement_from_8000(self):
        request = self._full_claim([8000])
        agreement = request.service_agreement_id
        self.assertEqual(request.state, 'agreement_pending')
        self.assertEqual(agreement.amount, 8000)
        self.assertEqual(agreement.period_months, 6)
        self.assertEqual(agreement.start_date, request.exam_clear_date)
        self.assertEqual(agreement.employee_id, self.engineer)
        self.assertEqual(set(request.expense_ids.mapped('state')), {'cert_approval'})
        with self.assertRaises(UserError):
            request.expense_ids.action_finance_approved()

    def test_agreement_tier_follows_amount(self):
        self.assertEqual(self._full_claim([15000, 5000]).service_agreement_id.period_months, 12)
        self.assertEqual(self._full_claim([50001]).service_agreement_id.period_months, 18)

    def test_paper_signature_releases_claim_to_finance(self):
        request = self._full_claim([8000])
        agreement = request.service_agreement_id
        agreement.action_mark_signed()
        self.assertEqual(agreement.state, 'active')
        self.assertEqual(agreement.signed_date, self.today)
        self.assertEqual(request.state, 'finance_approval')
        self.assertEqual(set(request.expense_ids.mapped('state')), {'finance_approval'})
        request.expense_ids.action_finance_approved()
        self.assertEqual(request.state, 'reimbursed')
        with self.assertRaises(UserError):
            agreement.action_mark_signed()

    @mute_logger('odoo.addons.bxi_certification_reimbursement.models.bxi_service_agreement')
    def test_failed_sending_is_reported(self):
        # The agreement cannot be rendered as a PDF: sending fails and HR is asked to act.
        Report = type(self.env['ir.actions.report'])
        with patch.object(Report, '_render_qweb_pdf', lambda *args, **kwargs: (b'<html/>', 'html')):
            request = self._full_claim([8000])
        agreement = request.service_agreement_id
        self.assertEqual(agreement.state, 'draft')
        self.assertFalse(agreement.sign_request_id)
        self.assertTrue(agreement.message_ids.filtered(lambda m: 'could not be sent' in m.body))
        self.assertTrue(agreement.activity_ids)

    def test_refusing_claim_cancels_agreement(self):
        request = self._full_claim([8000])
        request._action_refuse('Changed my mind')
        self.assertEqual(request.service_agreement_id.state, 'cancelled')

    # ── Electronic signature ─────────────────────────────────────────────
    def test_send_for_signature(self):
        agreement = self._create_agreement()
        agreement.action_send_for_signature()
        sign_request = agreement.sign_request_id
        self.assertEqual(agreement.state, 'sent')
        self.assertEqual(sign_request.state, 'sent')
        self.assertEqual(sign_request.reference_doc, agreement)
        self.assertEqual(sign_request.request_item_ids.partner_id, self.engineer.work_contact_id)
        self.assertEqual(len(sign_request.template_id.sign_item_ids), 2)
        url = agreement._get_portal_sign_url()
        self.assertIn(f'/sign/document/{sign_request.id}/', url)
        action = agreement.action_open_sign_request()
        self.assertEqual(action['res_id'], sign_request.id)

    def test_send_requires_email(self):
        self.engineer.work_contact_id.email = False
        agreement = self._create_agreement()
        with self.assertRaises(UserError):
            agreement.action_send_for_signature()

    def test_cannot_send_active_agreement(self):
        agreement = self._create_agreement(state='active')
        with self.assertRaises(UserError):
            agreement.action_send_for_signature()

    def test_portal_sign_url_only_while_sent(self):
        self.assertFalse(self._create_agreement()._get_portal_sign_url())

    def test_electronic_signature_releases_claim(self):
        request = self._full_claim([8000])
        agreement = request.service_agreement_id
        agreement.action_send_for_signature()
        sign_request = agreement.sign_request_id
        sign_request.request_item_ids.write({'state': 'completed'})
        with patch.object(type(sign_request), '_send_completed_documents', lambda self: None):
            sign_request._sign()
        self.assertEqual(agreement.state, 'active')
        self.assertEqual(request.state, 'finance_approval')

    def test_paper_signature_cancels_pending_e_signature(self):
        agreement = self._create_agreement()
        agreement.action_send_for_signature()
        agreement.action_mark_signed()
        self.assertEqual(agreement.sign_request_id.state, 'canceled')

    def test_cancel_agreement(self):
        agreement = self._create_agreement()
        agreement.action_send_for_signature()
        agreement.action_cancel()
        self.assertEqual(agreement.state, 'cancelled')
        self.assertEqual(agreement.sign_request_id.state, 'canceled')
        with self.assertRaises(UserError):
            self._create_agreement(state='active').action_cancel()

    # ── Recovery and completion ──────────────────────────────────────────
    def test_recover_and_waive(self):
        agreement = self._create_agreement(state='active')
        agreement.action_mark_recovered()
        self.assertEqual(agreement.state, 'recovered')
        with self.assertRaises(UserError):
            agreement.action_mark_recovered()
        agreement = self._create_agreement(state='active')
        agreement.action_waive()
        self.assertEqual(agreement.state, 'waived')
        with self.assertRaises(UserError):
            self._create_agreement().action_waive()

    def test_completion_cron(self):
        finished = self._create_agreement(start_date=self.today - timedelta(days=200), state='active')
        running = self._create_agreement(start_date=self.today - timedelta(days=10), state='active')
        self.env['bxi.service.agreement']._cron_complete_agreements()
        self.assertEqual(finished.state, 'completed')
        self.assertEqual(running.state, 'active')

    def test_employee_sees_only_own_agreements(self):
        own = self._create_agreement()
        other = self._create_agreement(employee_id=self.manager.id)
        Agreement = self.env['bxi.service.agreement'].with_user(self.engineer.user_id)
        self.assertEqual(Agreement.search([('id', 'in', (own | other).ids)]), own)
