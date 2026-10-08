from datetime import timedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, new_test_user, tagged

from .common import ConveyanceCommon


@tagged('post_install', '-at_install')
class TestApproval(ConveyanceCommon):

    def _approve(self, claim, user):
        claim.with_user(user).action_conveyance_approve()

    def test_auto_up_to_threshold_rm_only(self):
        claim = self._submit(self._claim(self.product_auto, employee=self.junior, total_amount_currency=1000))
        self.assertEqual(claim.conveyance_approval_line_ids.mapped('role'), ['rm'])
        self.assertEqual(claim.conveyance_approval_line_ids.approver_user_id, self.manager.user_id)
        # RM approval is initiated automatically.
        self.assertTrue(claim.activity_ids.filtered(lambda act: act.user_id == self.manager.user_id))

    def test_auto_above_threshold_rm_and_hr(self):
        claim = self._submit(self._claim(self.product_auto, employee=self.junior, total_amount_currency=1000.01))
        self.assertEqual(claim.conveyance_approval_line_ids.mapped('role'), ['rm', 'hr'])

    def test_auto_threshold_for_the_day(self):
        first = self._submit(self._claim(self.product_auto, employee=self.junior, total_amount_currency=600))
        self.assertEqual(first.conveyance_approval_line_ids.mapped('role'), ['rm'])
        # Splitting the day into several claims does not avoid the HR approval.
        second = self._submit(self._claim(self.product_auto, employee=self.junior, total_amount_currency=600))
        self.assertEqual(second.conveyance_approval_line_ids.mapped('role'), ['rm', 'hr'])
        self.assertIn('total', second.conveyance_policy_note)
        # Another day starts again.
        other_day = self._last_day(lambda day: day.weekday() < 5 and day < self.workday)
        third = self._submit(self._claim(self.product_auto, employee=self.junior, total_amount_currency=600,
                                         date=other_day))
        self.assertEqual(third.conveyance_approval_line_ids.mapped('role'), ['rm'])

    def test_taxi_above_threshold_rm_only(self):
        # The threshold is the auto-rickshaw rule.
        claim = self._submit(self._claim(self.product_taxi, total_amount_currency=2500))
        self.assertEqual(claim.conveyance_approval_line_ids.mapped('role'), ['rm'])

    def test_rm_then_hr_then_finance(self):
        claim = self._submit(self._claim(self.product_auto, employee=self.junior, total_amount_currency=1500))
        with self.assertRaisesRegex(UserError, 'not allowed'):
            self._approve(claim, self.hr_user)
        self._approve(claim, self.manager.user_id)
        self.assertEqual(claim.state, 'conveyance_approval')
        with self.assertRaisesRegex(UserError, 'not allowed'):
            self._approve(claim, self.manager.user_id)
        self._approve(claim, self.hr_user)
        self.assertEqual(claim.state, 'finance_approval')
        self.assertEqual(claim.conveyance_approval_line_ids.mapped('state'), ['approved', 'approved'])

    def test_company_hr_responsible(self):
        self.company.conveyance_hr_user_id = self.hr_user
        claim = self._submit(self._claim(self.product_auto, employee=self.junior, total_amount_currency=1500))
        self.assertEqual(claim.conveyance_approval_line_ids[1].approver_user_id, self.hr_user)

    def test_employee_cannot_approve_own_claim(self):
        claim = self._submit(self._claim(self.product_2w))
        with self.assertRaisesRegex(UserError, 'not allowed'):
            self._approve(claim, self.employee.user_id)
        with self.assertRaises(Exception):
            self._approve(claim, self.outsider)

    def test_claims_to_approve(self):
        claim = self._submit(self._claim(self.product_2w))
        to_approve = self.env['hr.expense'].with_user(self.manager.user_id).search(
            [('conveyance_can_approve', '=', True)])
        self.assertIn(claim, to_approve)
        self.assertFalse(self.env['hr.expense'].with_user(self.hr_user).search(
            [('conveyance_can_approve', '=', True), ('id', '=', claim.id)]))

    def test_refused_with_reason(self):
        claim = self._submit(self._claim(self.product_2w))
        action = claim.with_user(self.manager.user_id).action_conveyance_refuse()
        wizard = self.env['bxi.conveyance.refuse.wizard'].with_user(self.manager.user_id).with_context(
            action['context']).create({'reason': 'Commute between residence and workplace'})
        wizard.action_refuse()
        self.assertEqual(claim.state, 'refused')
        self.assertEqual(claim.conveyance_refuse_reason, 'Commute between residence and workplace')
        self.assertEqual(claim.conveyance_approval_line_ids.state, 'refused')

    def test_employee_without_manager(self):
        self.employee.parent_id = False
        with self.assertRaisesRegex(UserError, 'no Reporting Manager'):
            self._submit(self._claim(self.product_2w))

    def test_regular_expense_unchanged(self):
        product = self.env['product.product'].create({
            'name': 'Stationery', 'can_be_expensed': True, 'type': 'service', 'standard_price': 0,
        })
        expense = self.env['hr.expense'].with_user(self.employee.user_id).create({
            'name': 'Pens', 'product_id': product.id, 'employee_id': self.employee.id,
            'total_amount_currency': 100,
        })
        expense.with_user(self.employee.user_id).action_submit()
        self.assertEqual(expense.state, 'finance_approval')
        self.assertFalse(expense.conveyance_approval_line_ids)

    def test_draft_reminder(self):
        claim = self._claim(self.product_2w, date=self.today - timedelta(days=40))
        self.env['hr.expense']._cron_conveyance_claim_reminder()
        self.assertTrue(claim.sudo().activity_ids.filtered(lambda act: act.user_id == self.employee.user_id))

    def test_admin_approves_on_behalf(self):
        admin = new_test_user(self.env, login='lc_test_admin', name='Conveyance Admin',
                              groups='base.group_user,bxi_local_conveyance.group_conveyance_admin')
        claim = self._submit(self._claim(self.product_auto, employee=self.junior, total_amount_currency=1500))
        self.assertFalse(claim.with_user(admin).conveyance_can_approve)
        claim.with_user(admin).action_conveyance_approve_on_behalf()
        rm_line, hr_line = claim.conveyance_approval_line_ids
        self.assertEqual(rm_line.state, 'approved')
        self.assertEqual(rm_line.done_by_user_id, admin)
        self.assertIn('on behalf of Manager', rm_line.comment)
        self.assertEqual(claim.state, 'conveyance_approval')
        claim.with_user(admin).action_conveyance_approve_on_behalf()
        self.assertIn('on behalf of HR', hr_line.comment)
        self.assertEqual(claim.state, 'finance_approval')
        self.assertEqual(claim.conveyance_status, 'finance_approval')

    def test_approve_on_behalf_restricted(self):
        claim = self._submit(self._claim(self.product_2w))
        with self.assertRaises(AccessError):
            claim.with_user(self.hr_user).action_conveyance_approve_on_behalf()
        # Not even an administrator approves their own claim.
        self.employee.user_id.group_ids |= self.env.ref('bxi_local_conveyance.group_conveyance_admin')
        with self.assertRaisesRegex(UserError, 'own claim'):
            claim.with_user(self.employee.user_id).action_conveyance_approve_on_behalf()

    def test_form_shows_conveyance_status(self):
        claim = self._submit(self._claim(self.product_2w))
        self.assertEqual(claim.conveyance_status, 'conveyance_approval')
        with Form(claim.sudo()) as form:
            self.assertEqual(form.conveyance_status, 'conveyance_approval')
