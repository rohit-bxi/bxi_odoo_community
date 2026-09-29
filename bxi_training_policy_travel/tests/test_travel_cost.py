from odoo.addons.bxi_training_policy.tests.common import TrainingCommon
from odoo.exceptions import ValidationError
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestTravelCost(TrainingCommon):

    def _travel(self, training, amount, employee=None):
        india = self.env.ref('base.in')
        travel = self.env['travel.request'].create({
            'employee_id': (employee or self.employee).id,
            'training_request_id': training.id if training else False,
            'travel_purpose': 'Training', 'from_country': india.id, 'from_city': 'Pune',
            'to_country': india.id, 'to_city': 'Bengaluru', 'departure_date': self.today,
        })
        self.env['travel.request.expense.line'].create({
            'travel_request_id': travel.id, 'amount': amount, 'expense_type': 'travel', 'description': 'Flight',
        })
        return travel

    def test_approved_travel_counts_in_actual_cost(self):
        training = self._ready(self._new_training(fee=40000, lodging=0))
        self._complete(training)
        travel = self._travel(training, 12000)
        self.assertEqual(training.travel_cost, 0)
        travel.sudo().state = 'approve'
        self.assertEqual(training.travel_cost, 12000)
        training.cost_line_ids.filtered(lambda line: line.paid_by == 'company').with_user(self.hr_user).actual_amount = 40000
        self.assertEqual(training.actual_cost, 52000)
        training.with_user(self.es_user).action_settle_without_claim()
        self.assertEqual(training.agreement_id.amount, 52000)

    def test_travel_of_another_employee_rejected(self):
        training = self._new_training()
        with self.assertRaises(ValidationError):
            self._travel(training, 1000, employee=self.manager)
