from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import ConveyanceCommon


@tagged('post_install', '-at_install')
class TestDomesticTransfer(ConveyanceCommon):

    def _transfer(self, employee=None, option='drive'):
        return self.env['bxi.conveyance.transfer'].with_user(self.hr_user).create({
            'employee_id': (employee or self.employee).id,
            'from_city': 'Delhi',
            'to_city': 'Jaipur',
            'transfer_date': self.workday,
            'vehicle_option': option,
        })

    def test_drive_paid_per_km_rm_and_hr(self):
        transfer = self._transfer()
        claim = self._submit(self._claim(self.product_transfer_4w, conveyance_transfer_id=transfer.id,
                                         conveyance_distance=280))
        self.assertEqual(claim.total_amount, 1400.0)
        self.assertEqual((claim.conveyance_from, claim.conveyance_to), ('Delhi', 'Jaipur'))
        # Intercity: processed through HR (and then Finance).
        self.assertEqual(claim.conveyance_approval_line_ids.mapped('role'), ['rm', 'hr'])
        self.assertEqual(transfer.claim_id, claim)
        self.assertFalse(self.env['bxi.conveyance.transfer']._get_claimable(self.employee))

    def test_transfer_on_weekend_and_out_of_city(self):
        transfer = self._transfer()
        self._submit(self._claim(self.product_transfer_2w, conveyance_transfer_id=transfer.id,
                                 date=self.weekend_day))

    def test_needs_transfer(self):
        with self.assertRaisesRegex(UserError, 'select the domestic transfer'):
            self._submit(self._claim(self.product_transfer_4w))
        with self.assertRaisesRegex(UserError, 'not the employee'):
            self._submit(self._claim(self.product_transfer_4w, conveyance_transfer_id=self._transfer(self.junior).id))

    def test_not_with_vehicle_movement(self):
        transfer = self._transfer(option='shipment')
        with self.assertRaisesRegex(UserError, 'cannot be claimed as well'):
            self._submit(self._claim(self.product_transfer_4w, conveyance_transfer_id=transfer.id))

    def test_one_vehicle_only(self):
        transfer = self._transfer()
        self._submit(self._claim(self.product_transfer_4w, conveyance_transfer_id=transfer.id))
        with self.assertRaisesRegex(UserError, 'one vehicle only'):
            self._submit(self._claim(self.product_transfer_2w, conveyance_transfer_id=transfer.id))

    def test_refused_claim_frees_the_transfer(self):
        transfer = self._transfer()
        claim = self._submit(self._claim(self.product_transfer_4w, conveyance_transfer_id=transfer.id))
        claim.sudo().state = 'refused'
        self._submit(self._claim(self.product_transfer_4w, conveyance_transfer_id=transfer.id))

    def test_employee_sees_own_transfer_only(self):
        transfer = self._transfer()
        Transfer = self.env['bxi.conveyance.transfer']
        self.assertEqual(Transfer.with_user(self.employee.user_id).search([]), transfer)
        self.assertEqual(Transfer.with_user(self.manager.user_id).search([]), transfer)
        self.assertFalse(Transfer.with_user(self.junior.user_id).search([]))
