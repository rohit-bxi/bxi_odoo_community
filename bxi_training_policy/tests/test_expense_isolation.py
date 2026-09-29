from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import TrainingCommon


@tagged('post_install', '-at_install')
class TestExpenseIsolation(TrainingCommon):

    def test_training_products_hidden_from_portal_claims(self):
        domain = self.env['hr.expense']._portal_expense_product_domain()
        products = self.env['product.product'].search(domain)
        self.assertNotIn(self.fee_product, products)
        self.assertNotIn(self.lodging_product, products)

    def test_training_expense_not_submitted_on_its_own(self):
        expense = self.env['hr.expense'].with_user(self.employee.user_id).create({
            'name': 'Course fee', 'product_id': self.fee_product.id, 'total_amount_currency': 1000,
            'employee_id': self.employee.id,
        })
        with self.assertRaisesRegex(UserError, 'Specialized Training'):
            expense.action_submit()

    def test_claim_line_needs_completed_training(self):
        training = self._nominate(self._new_training())
        with self.assertRaisesRegex(UserError, 'completed'):
            self.env['hr.expense'].with_user(self.employee.user_id).create({
                'name': 'Hotel', 'product_id': self.lodging_product.id, 'total_amount_currency': 1000,
                'employee_id': self.employee.id, 'training_request_id': training.id,
            })

    def test_finance_waits_for_es(self):
        training = self._ready(self._new_training(fee=10000, lodging=5000))
        self._complete(training)
        self._add_claim_line(training, self.lodging_product, 4000)
        training.with_user(self.employee.user_id).action_submit_claim()
        training.sudo().expense_ids.state = 'finance_approval'  # forced past the approvals
        with self.assertRaisesRegex(UserError, 'Employee Services'):
            training.expense_ids.with_user(self.finance_user).action_finance_approved()

    def test_finance_refusal_refers_back(self):
        training = self._ready(self._new_training(fee=10000, lodging=5000))
        self._complete(training)
        self._add_claim_line(training, self.lodging_product, 4000)
        training.with_user(self.employee.user_id).action_submit_claim()
        self._approve_claim(training)
        training.expense_ids.with_user(self.finance_user).action_refuse()
        self.assertEqual(training.state, 'completed')
        self.assertEqual(training.expense_ids.state, 'draft')
