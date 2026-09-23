from datetime import timedelta

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CertificationCommon


@tagged('post_install', '-at_install')
class TestClaimApproval(CertificationCommon):

    # ── Claim validation ─────────────────────────────────────────────────
    def test_claim_only_on_pre_approved_request(self):
        request = self._prepare_claim(self._new_request(), [1000])
        with self.assertRaises(UserError):
            request.action_submit_claim()

    def _approved_request(self, **vals):
        return self._pre_approve(self._new_request(**vals))

    def test_claim_requires_exam_date(self):
        request = self._approved_request()
        request.write({'attempt_passed': True, 'certificate_attachment_ids': [(6, 0, self.pdf.ids)]})
        self._add_lines(request, [1000])
        with self.assertRaises(UserError):
            request.action_submit_claim()

    def test_failed_attempt_cannot_be_claimed(self):
        request = self._prepare_claim(self._approved_request(), [1000])
        request.attempt_passed = False
        with self.assertRaises(UserError):
            request.action_submit_claim()

    def test_claim_requires_certificate(self):
        request = self._prepare_claim(self._approved_request(), [1000])
        request.certificate_attachment_ids = False
        with self.assertRaises(UserError):
            request.action_submit_claim()

    def test_claim_requires_lines(self):
        request = self._prepare_claim(self._approved_request(), [])
        with self.assertRaises(UserError):
            request.action_submit_claim()

    def test_claim_total_must_be_positive(self):
        request = self._prepare_claim(self._approved_request(), [0])
        with self.assertRaises(UserError):
            request.action_submit_claim()

    def test_only_certification_categories(self):
        request = self._prepare_claim(self._approved_request(), [1000])
        self._add_lines(request, [200], products=[self.meals])
        with self.assertRaises(UserError):
            request.action_submit_claim()

    def test_lines_must_belong_to_employee(self):
        request = self._prepare_claim(self._approved_request(), [1000])
        request.expense_ids.employee_id = self.manager
        with self.assertRaises(UserError):
            request.action_submit_claim()

    def test_claim_blocked_after_resignation(self):
        request = self._prepare_claim(self._approved_request(), [1000])
        self.env['employee.resignation'].create({
            'employee_id': self.engineer.id, 'last_working_day': self.today + timedelta(days=30),
            'reason': 'personal', 'resignation_body': '<p>x</p>', 'state': 'approved',
        })
        with self.assertRaises(UserError):
            request.action_submit_claim()

    def test_missing_cost_centre_blocks_claim(self):
        self.band4.cost_center_id = False
        with self.assertRaises(UserError):
            self._claim(self._approved_request(), [1000])

    def test_approver_without_user_blocks_claim(self):
        self.band4.user_id = False
        with self.assertRaises(UserError):
            self._claim(self._approved_request(), [1000])

    def test_udemy_claim_needs_approval_email_and_cap(self):
        request = self._pre_approve(self._new_request(self.udemy))
        request.with_user(self.academy_head.user_id).udemy_max_amount = 3000
        request.with_user(self.academy_head.user_id).action_academy_approve()
        self._prepare_claim(request, [2500])
        with self.assertRaises(UserError):
            request.action_submit_claim()  # academy approval email missing
        request.pre_approval_attachment_ids = self.pdf
        self._add_lines(request, [1000])
        with self.assertRaises(UserError):
            request.action_submit_claim()  # 3500 exceeds the approved 3000
        request.expense_ids.filtered(lambda exp: exp.total_amount == 1000).unlink()
        request.action_submit_claim()
        self.assertEqual(request.state, 'claim_approval')

    # ── Submitted claim ──────────────────────────────────────────────────
    def test_submitted_claim(self):
        request = self._claim(self._approved_request(), [4000, 500])
        self.assertEqual(request.state, 'claim_approval')
        self.assertEqual(request.claim_total, 4500)
        self.assertEqual(request.claim_submit_date, self.today)
        self.assertEqual(request.claim_age_days, 10)
        self.assertEqual(request.band4_head_id, self.band4)
        self.assertEqual(request.cost_center_id, self.cost_center)
        self.assertEqual(set(request.expense_ids.mapped('state')), {'cert_approval'})
        for expense in request.expense_ids:
            self.assertEqual(expense.analytic_distribution, {str(self.cost_center.id): 100})
        self.assertEqual(request.current_approver_id, self.band4)
        self.assertTrue(request.activity_ids.filtered(lambda a: a.user_id == self.band4.user_id))

    # ── Approval matrix ──────────────────────────────────────────────────
    def test_up_to_5000_needs_band4_only(self):
        request = self._claim(self._approved_request(), [5000])
        self.assertEqual(request.approval_line_ids.mapped('role'), ['band4'])

    def test_above_5000_needs_band2_then_band4(self):
        request = self._claim(self._approved_request(), [5001])
        self.assertEqual(request.approval_line_ids.mapped('role'), ['band2', 'band4'])
        self.assertEqual(request.approval_line_ids.mapped('approver_id'), self.band2 | self.band4)

    def test_band4_limit_is_configurable(self):
        self.env['ir.config_parameter'].set_param('bxi_certification_reimbursement.band4_limit', 10000)
        request = self._claim(self._approved_request(), [6000])
        self.assertEqual(request.approval_line_ids.mapped('role'), ['band4'])

    def test_not_in_approved_list_needs_band3_and_academy(self):
        request = self._claim(self._approved_request(certification_id=False, certification_name='Unlisted',
                                                     certifying_body='Body'), [1000])
        self.assertEqual(request.approval_line_ids.mapped('role'), ['band3', 'band4', 'academy'])
        self.assertEqual(request.approval_line_ids.mapped('approver_id'),
                         self.band3 | self.band4 | self.academy_head)

    def test_not_in_approved_list_needs_academy_head(self):
        self.lob.academy_head_id = False
        request = self._prepare_claim(self._pre_approve(self._new_request(False)), [1000])
        with self.assertRaises(UserError):
            request.action_submit_claim()

    def test_late_claim_goes_to_skip_manager(self):
        request = self._claim(self._approved_request(), [1000], days_ago=91)
        self.assertTrue(request.is_late_claim)
        self.assertEqual(request.claim_age_days, 91)
        self.assertEqual(request.approval_line_ids.mapped('role'), ['skip_manager', 'band4'])
        self.assertEqual(request.approval_line_ids[0].approver_id, self.band2)

    def test_claim_at_90_days_is_not_late(self):
        request = self._claim(self._approved_request(), [1000], days_ago=90)
        self.assertFalse(request.is_late_claim)
        self.assertEqual(request.approval_line_ids.mapped('role'), ['band4'])

    def test_claim_days_limit_is_configurable(self):
        self.env['ir.config_parameter'].set_param('bxi_certification_reimbursement.claim_days_limit', 30)
        request = self._claim(self._approved_request(), [1000], days_ago=31)
        self.assertTrue(request.is_late_claim)

    def test_same_approver_is_not_repeated(self):
        # Late claim above 5000: the skip manager is also the Band 2 head.
        request = self._claim(self._approved_request(), [6000], days_ago=91)
        self.assertEqual(request.approval_line_ids.mapped('role'), ['skip_manager', 'band4'])
        # The Band 4 head is also the academy head.
        self.lob.academy_head_id = self.band4
        request = self._claim(self._pre_approve(self._new_request(False)), [1000])
        self.assertEqual(request.approval_line_ids.mapped('role'), ['band3', 'band4'])

    def test_band4_head_falls_back_to_head_of_line(self):
        self.band3.parent_id = self.ceo
        self.ceo.cost_center_id = self.cost_center
        request = self._claim(self._approved_request(), [1000])
        self.assertEqual(request.band4_head_id, self.ceo)
        self.assertEqual(request.approval_line_ids.approver_id, self.ceo)

    # ── Approving ────────────────────────────────────────────────────────
    def test_approvals_follow_the_order(self):
        request = self._claim(self._approved_request(), [6000])
        self.assertFalse(request.with_user(self.band4.user_id).can_approve)
        with self.assertRaises(UserError):
            request.with_user(self.band4.user_id).action_approve_claim()
        request.with_user(self.band2.user_id).action_approve_claim()
        first = request.approval_line_ids[0]
        self.assertEqual(first.state, 'approved')
        self.assertEqual(first.done_by_user_id, self.band2.user_id)
        self.assertTrue(first.date)
        self.assertEqual(request.current_approver_id, self.band4)
        self.assertEqual(request.state, 'claim_approval')
        request.with_user(self.band4.user_id).action_approve_claim()
        self.assertEqual(request.state, 'finance_approval')
        self.assertEqual(set(request.expense_ids.mapped('state')), {'finance_approval'})

    def test_employee_cannot_approve_own_claim(self):
        request = self._claim(self._approved_request(), [1000])
        with self.assertRaises(UserError):
            request.with_user(self.engineer.user_id).action_approve_claim()

    # ── Refusal ──────────────────────────────────────────────────────────
    def test_refuse_claim(self):
        request = self._claim(self._approved_request(), [1000])
        self.env['bxi.certification.refuse.wizard'].with_user(self.band4.user_id).create({
            'request_id': request.id, 'reason': 'Wrong receipt',
        }).action_refuse()
        self.assertEqual(request.state, 'refused')
        self.assertEqual(request.approval_line_ids.state, 'refused')
        self.assertEqual(request.approval_line_ids.comment, 'Wrong receipt')
        self.assertEqual(set(request.expense_ids.mapped('state')), {'refused'})
        self.assertFalse(request.activity_ids)

    def test_only_current_approver_refuses(self):
        request = self._claim(self._approved_request(), [6000])
        wizard = self.env['bxi.certification.refuse.wizard'].with_user(self.band4.user_id).create({
            'request_id': request.id, 'reason': 'No',
        })
        with self.assertRaises(UserError):
            wizard.action_refuse()

    def test_employee_cannot_refuse(self):
        request = self._new_request()
        wizard = self.env['bxi.certification.refuse.wizard'].with_user(self.engineer.user_id).create({
            'request_id': request.id, 'reason': 'No',
        })
        with self.assertRaises(UserError):
            wizard.action_refuse()

    def test_finance_can_refuse_at_finance_stage(self):
        request = self._full_claim([1000])
        finance = self.env['res.users'].create({
            'name': 'Finance', 'login': 'cert_test_finance',
            'group_ids': [(6, 0, self.env.ref('hr_expense.group_hr_expense_manager').ids)],
        })
        request.with_user(finance)._check_can_refuse()
        with self.assertRaises(UserError):
            request.with_user(self.band4.user_id)._check_can_refuse()

    # ── Finance ──────────────────────────────────────────────────────────
    def test_finance_approval_reimburses(self):
        request = self._full_claim([1000, 200])
        request.expense_ids[0].action_finance_approved()
        self.assertEqual(request.state, 'finance_approval', "Waits for all lines")
        request.expense_ids[1].action_finance_approved()
        self.assertEqual(request.state, 'reimbursed')

    def test_finance_refusal_refuses_request(self):
        request = self._full_claim([1000])
        request.expense_ids.action_refuse()
        self.assertEqual(request.state, 'refused')
        self.assertTrue(request.refuse_reason)

    def test_finance_cannot_approve_before_band_approvals(self):
        request = self._claim(self._approved_request(), [1000])
        request.expense_ids.write({'state': 'finance_approval'})
        with self.assertRaises(UserError):
            request.expense_ids.action_finance_approved()

    # ── Expense guards ───────────────────────────────────────────────────
    def test_certification_expense_not_submitted_directly(self):
        expense = self.env['hr.expense'].create({
            'name': 'Fee', 'product_id': self.exam_fee.id, 'employee_id': self.engineer.id,
            'total_amount_currency': 1000,
        })
        with self.assertRaises(UserError):
            expense.action_submit()

    def test_other_expenses_still_submitted(self):
        expense = self.env['hr.expense'].create({
            'name': 'Lunch', 'product_id': self.meals.id, 'employee_id': self.engineer.id,
            'total_amount_currency': 100,
        })
        expense.action_submit()
        self.assertEqual(expense.state, 'finance_approval')

    def test_submitted_lines_are_locked(self):
        request = self._claim(self._approved_request(), [1000])
        admin = self.env.ref('base.user_admin')
        with self.assertRaises(UserError):
            request.expense_ids.with_user(admin).write({'total_amount_currency': 99999})
        request.expense_ids.with_user(admin).write({'description': 'Notes are still allowed'})
        request.expense_ids.write({'total_amount_currency': 1000})  # the workflow (superuser) may

    def test_portal_expense_categories_exclude_certification(self):
        domain = self.env['hr.expense']._portal_expense_product_domain()
        products = self.env['product.product'].search(domain)
        self.assertIn(self.meals, products)
        self.assertNotIn(self.exam_fee, products)

    def test_claim_lines_action(self):
        request = self._claim(self._approved_request(), [1000])
        action = request.action_view_expenses()
        self.assertEqual(self.env['hr.expense'].search(action['domain']), request.expense_ids)
