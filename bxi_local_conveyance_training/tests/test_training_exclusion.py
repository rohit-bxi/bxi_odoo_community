from datetime import timedelta

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.bxi_local_conveyance.tests.common import ConveyanceCommon


@tagged('post_install', '-at_install')
class TestTrainingExclusion(ConveyanceCommon):

    def _training(self):
        return self.env['bxi.training.request'].sudo().create({
            'employee_id': self.employee.id,
            'training_name': 'Advanced Kubernetes',
            'location': 'Delhi',
            'purpose': 'Cloud migration project',
            'start_date': self.workday - timedelta(days=2),
            'end_date': self.workday + timedelta(days=2),
        })

    def test_no_conveyance_during_training(self):
        training = self._training()
        training.state = 'in_training'
        with self.assertRaisesRegex(UserError, 'training programs'):
            self._submit(self._claim(self.product_2w))

    def test_conveyance_after_training(self):
        training = self._training()
        training.write({'state': 'completed', 'end_date': self.workday - timedelta(days=1)})
        self._submit(self._claim(self.product_2w))

    def test_cancelled_training_ignored(self):
        self._training().state = 'cancelled'
        self._submit(self._claim(self.product_2w))
