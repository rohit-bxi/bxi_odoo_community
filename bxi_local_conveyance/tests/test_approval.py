from datetime import timedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, new_test_user, tagged

from .common import ConveyanceCommon


@tagged('post_install', '-at_install')
class TestApproval(ConveyanceCommon):

    def _approve(self, claim, user):
        claim.with_user(user).action_conveyance_approve()

    def test_every_claim_rm_finance_hr(self):
        for claim in (
            self._claim(self.product_auto, employee=self.junior, total_amount_currency=200),
            self._claim(self.product_taxi, total_amount_currency=2500),
            self._claim(self.product_2w),
        ):
            self._submit(claim)
            self.assertEqual(claim.conveyance_approval_line_ids.mapped('role'), ['rm', 'finance', 'hr'])
            self.assertEqual(claim.conveyance_approval_line_ids[0].approver_user_id, self.manager.user_id)
            self.assertEqual(claim.conveyance_status, 'rm_approval')
            # RM approval is initiated automatically.
            self.assertTrue(claim.activity_ids.filtered(lambda act: act.user_id == self.manager.user_id))

    def test_rm_then_finance_then_hr(self):
        claim = self._submit(self._claim(self.product_auto, employee=self.junior, total_amount_currency=1500))
        for user in (self.finance_user, self.hr_user):
            with self.assertRaisesRegex(UserError, 'not allowed'):
                self._approve(claim, user)
        self._approve(claim, self.manager.user_id)
        self.assertEqual(claim.state, 'conveyance_approval')
        self.assertEqual(claim.conveyance_status, 'finance_approval')
        self.assertTrue(claim.activity_ids.filtered(lambda act: act.user_id == self.finance_user))
        for user in (self.manager.user_id, self.hr_user):
            with self.assertRaisesRegex(UserError, 'not allowed'):
                self._approve(claim, user)
        self._approve(claim, self.finance_user)
        self.assertEqual(claim.conveyance_status, 'hr_approval')
        self.assertTrue(claim.activity_ids.filtered(lambda act: act.user_id == self.hr_user))
        with self.assertRaisesRegex(UserError, 'not allowed'):
            self._approve(claim, self.finance_user)
        self._approve(claim, self.hr_user)
        self.assertEqual(claim.state, 'approved')
        self.assertEqual(claim.conveyance_status, 'approved')
        self.assertEqual(claim.conveyance_approval_line_ids.mapped('state'), ['approved'] * 3)
        self.assertFalse(claim.activity_ids)

    def test_company_responsibles(self):
        self.company.conveyance_finance_user_id = self.finance_user
        self.company.conveyance_hr_user_id = self.hr_user
        claim = self._submit(self._claim(self.product_2w))
        self.assertEqual(claim.conveyance_approval_line_ids.mapped('approver_user_id'),
                         self.manager.user_id | self.finance_user | self.hr_user)
        # Another Finance officer is not the Finance Responsible.
        other_finance = new_test_user(self.env, login='lc_test_finance_2', name='Other Finance',
                                      groups='base.group_user,bxi_local_conveyance.group_conveyance_finance')
        self._approve(claim, self.manager.user_id)
        with self.assertRaisesRegex(UserError, 'not allowed'):
            self._approve(claim, other_finance)
        self._approve(claim, self.finance_user)

    def test_same_user_approves_once(self):
        self.company.conveyance_hr_user_id = self.manager.user_id
        claim = self._submit(self._claim(self.product_2w))
        self.assertEqual(claim.conveyance_approval_line_ids.mapped('role'), ['rm', 'finance'])
        self._approve(claim, self.manager.user_id)
        self._approve(claim, self.finance_user)
        self.assertEqual(claim.state, 'approved')

    def test_finance_approve_button_blocked(self):
        claim = self._submit(self._claim(self.product_2w))
        with self.assertRaisesRegex(UserError, 'Approve button'):
            claim.sudo().action_finance_approved()

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
        for user in (self.finance_user, self.hr_user):
            self.assertFalse(self.env['hr.expense'].with_user(user).search(
                [('conveyance_can_approve', '=', True), ('id', '=', claim.id)]))
        self._approve(claim, self.manager.user_id)
        self.assertIn(claim, self.env['hr.expense'].with_user(self.finance_user).search(
            [('conveyance_can_approve', '=', True)]))

    def test_refused_with_reason(self):
        claim = self._submit(self._claim(self.product_2w))
        action = claim.with_user(self.manager.user_id).action_conveyance_refuse()
        wizard = self.env['bxi.conveyance.refuse.wizard'].with_user(self.manager.user_id).with_context(
            action['context']).create({'reason': 'Commute between residence and workplace'})
        wizard.action_refuse()
        self.assertEqual(claim.state, 'refused')
        self.assertEqual(claim.conveyance_refuse_reason, 'Commute between residence and workplace')
        self.assertEqual(claim.conveyance_approval_line_ids.mapped('state'), ['refused', 'pending', 'pending'])

    def test_finance_refuses(self):
        claim = self._submit(self._claim(self.product_2w))
        self._approve(claim, self.manager.user_id)
        claim.with_user(self.finance_user)._conveyance_refuse('Duplicate of a flexi basket claim')
        self.assertEqual(claim.state, 'refused')
        self.assertEqual(claim.conveyance_status, 'refused')
        self.assertEqual(claim.conveyance_approval_line_ids.mapped('state'), ['approved', 'refused', 'pending'])

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
        self.assertFalse(expense.conveyance_status)

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
        rm_line, finance_line, hr_line = claim.conveyance_approval_line_ids
        self.assertEqual(rm_line.state, 'approved')
        self.assertEqual(rm_line.done_by_user_id, admin)
        self.assertIn('on behalf of Manager', rm_line.comment)
        self.assertEqual(claim.conveyance_status, 'finance_approval')
        claim.with_user(admin).action_conveyance_approve_on_behalf()
        self.assertIn('on behalf of Finance', finance_line.comment)
        self.assertEqual(claim.conveyance_status, 'hr_approval')
        claim.with_user(admin).action_conveyance_approve_on_behalf()
        self.assertIn('on behalf of HR', hr_line.comment)
        self.assertEqual(claim.state, 'approved')
        self.assertEqual(claim.conveyance_status, 'approved')

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
        self.assertEqual(claim.conveyance_status, 'rm_approval')
        with Form(claim.sudo()) as form:
            self.assertEqual(form.conveyance_status, 'rm_approval')
