from datetime import timedelta

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import CertificationCommon


@tagged('post_install', '-at_install')
class TestCertificationRequest(CertificationCommon):

    # ── Creation and constraints ─────────────────────────────────────────
    def test_sequence_and_defaults(self):
        request = self.env['bxi.certification.request'].with_user(self.engineer.user_id).create({
            'certification_id': self.certification.id,
        })
        self.assertTrue(request.name.startswith('CERT/'))
        self.assertEqual(request.employee_id, self.engineer)
        self.assertEqual(request.state, 'draft')
        self.assertTrue(request.is_on_approved_list)
        self.assertEqual(request.currency_id, self.env.company.currency_id)

    def test_certification_or_name_required(self):
        with self.assertRaises(ValidationError):
            self.env['bxi.certification.request'].create({'employee_id': self.engineer.id})
        request = self._new_request(False)
        self.assertFalse(request.is_on_approved_list)
        self.assertEqual(request._get_certification_label(), 'Unlisted Cert')

    def test_exam_date_cannot_be_in_future(self):
        request = self._new_request()
        with self.assertRaises(ValidationError):
            request.exam_clear_date = self.today + timedelta(days=1)

    def test_is_udemy_follows_certification(self):
        self.assertTrue(self._new_request(self.udemy).is_udemy)
        self.assertFalse(self._new_request().is_udemy)

    # ── Pre-approval ─────────────────────────────────────────────────────
    def test_submit_to_reporting_manager(self):
        request = self._new_request()
        request.action_submit()
        self.assertEqual(request.state, 'rm_approval')
        self.assertEqual(request.manager_id, self.manager)
        self.assertEqual(request.lob_id, self.lob)
        self.assertTrue(request.activity_ids.filtered(lambda a: a.user_id == self.manager.user_id))
        with self.assertRaises(UserError):
            request.action_submit()

    def test_submit_requires_cost_centre_acknowledgement(self):
        with self.assertRaises(UserError):
            self._new_request(cost_centre_ack=False).action_submit()

    def test_submit_requires_reporting_manager(self):
        with self.assertRaises(UserError):
            self._new_request(employee=self.ceo).action_submit()

    def test_submit_requires_india_payroll(self):
        self.engineer.is_india_payroll = False
        with self.assertRaises(UserError):
            self._new_request().action_submit()

    def test_submit_blocked_after_resignation(self):
        self._resign(self.engineer)
        with self.assertRaises(UserError):
            self._new_request().action_submit()

    def test_only_reporting_manager_approves(self):
        request = self._new_request()
        request.action_submit()
        self.assertFalse(request.with_user(self.band2.user_id).can_approve)
        with self.assertRaises(UserError):
            request.with_user(self.band2.user_id).action_rm_approve()
        self.assertTrue(request.with_user(self.manager.user_id).can_approve)
        request.with_user(self.manager.user_id).action_rm_approve()
        self.assertEqual(request.state, 'approved')
        self.assertTrue(request.rm_approved_date)
        self.assertFalse(request.activity_ids.filtered(lambda a: a.user_id == self.manager.user_id))

    def test_certification_administrator_can_approve(self):
        request = self._new_request()
        request.action_submit()
        request.action_rm_approve()  # superuser is a certification administrator
        self.assertEqual(request.state, 'approved')

    def test_udemy_needs_academy_approval(self):
        request = self._pre_approve(self._new_request(self.udemy))
        self.assertEqual(request.state, 'academy_approval')
        academy = self.academy_head.user_id
        with self.assertRaises(UserError):
            request.with_user(academy).action_academy_approve()  # maximum amount missing
        with self.assertRaises(UserError):
            request.with_user(self.manager.user_id).action_academy_approve()
        request.with_user(academy).udemy_max_amount = 3000
        request.with_user(academy).action_academy_approve()
        self.assertEqual(request.state, 'approved')

    def test_refuse_pre_approval(self):
        request = self._new_request()
        request.action_submit()
        wizard = self.env['bxi.certification.refuse.wizard'].with_user(self.manager.user_id).create({
            'request_id': request.id, 'reason': 'Not needed for the project',
        })
        wizard.action_refuse()
        self.assertEqual(request.state, 'refused')
        self.assertEqual(request.refuse_reason, 'Not needed for the project')

    def test_refuse_wizard_action(self):
        action = self._new_request().action_open_refuse_wizard()
        self.assertEqual(action['res_model'], 'bxi.certification.refuse.wizard')
        self.assertTrue(action['context']['default_request_id'])

    # ── Cancel, reset and delete ─────────────────────────────────────────
    def test_cancel_removes_draft_lines(self):
        request = self._pre_approve(self._new_request())
        lines = self._add_lines(request, [100])
        request.action_cancel()
        self.assertEqual(request.state, 'cancelled')
        self.assertFalse(lines.exists())

    def test_cannot_cancel_after_claim(self):
        request = self._claim(self._pre_approve(self._new_request()), [1000])
        with self.assertRaises(UserError):
            request.action_cancel()

    def test_reset_to_draft(self):
        request = self._claim(self._pre_approve(self._new_request()), [1000])
        with self.assertRaises(UserError):
            request.action_reset_to_draft()
        request._action_refuse('Wrong receipt')
        request.action_reset_to_draft()
        self.assertEqual(request.state, 'draft')
        self.assertFalse(request.approval_line_ids)
        self.assertFalse(request.refuse_reason)
        self.assertFalse(request.claim_submit_date)
        self.assertEqual(set(request.expense_ids.mapped('state')), {'draft'})

    def test_unlink_only_draft_or_cancelled(self):
        draft = self._new_request()
        draft.unlink()
        submitted = self._new_request()
        submitted.action_submit()
        with self.assertRaises(UserError):
            submitted.unlink()
        submitted.action_cancel()
        submitted.unlink()

    # ── Write protection ─────────────────────────────────────────────────
    def test_employee_cannot_write_workflow_fields(self):
        request = self._new_request().with_user(self.engineer.user_id)
        for vals in ({'state': 'reimbursed'}, {'manager_id': self.band4.id}, {'udemy_max_amount': 99999},
                     {'cost_center_id': self.cost_center.id}):
            with self.assertRaises(AccessError):
                request.write(vals)

    def test_employee_cannot_change_approved_details(self):
        request = self._pre_approve(self._new_request())
        with self.assertRaises(UserError):
            request.with_user(self.engineer.user_id).write({'certification_id': self.udemy.id})
        with self.assertRaises(UserError):
            request.with_user(self.engineer.user_id).write({'estimated_cost': 1})
        request.with_user(self.engineer.user_id).write({'exam_clear_date': self.today})
        self.assertEqual(request.exam_clear_date, self.today)

    def test_employee_cannot_edit_submitted_request(self):
        request = self._new_request()
        request.action_submit()
        with self.assertRaises(UserError):
            request.with_user(self.engineer.user_id).write({'planned_exam_date': self.today})

    def test_academy_can_only_set_udemy_amount_during_its_approval(self):
        request = self._new_request(self.udemy)
        with self.assertRaises(AccessError):
            request.with_user(self.academy_head.user_id).write({'udemy_max_amount': 100})

    # ── Visibility ───────────────────────────────────────────────────────
    def test_record_rules(self):
        request = self._new_request()
        Request = self.env['bxi.certification.request']
        self.assertTrue(Request.with_user(self.engineer.user_id).search([('id', '=', request.id)]))
        self.assertFalse(Request.with_user(self.band2.user_id).search([('id', '=', request.id)]))
        request.action_submit()
        self.assertTrue(Request.with_user(self.manager.user_id).search([('id', '=', request.id)]))
        self.assertTrue(Request.with_user(self.academy_head.user_id).search([('id', '=', request.id)]),
                        "The academy sees requests of its Line of Business")

    def test_approver_sees_request_after_claim(self):
        request = self._claim(self._pre_approve(self._new_request()), [1000])
        Request = self.env['bxi.certification.request'].with_user(self.band4.user_id)
        self.assertTrue(Request.search([('id', '=', request.id)]))
