from datetime import date
from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGiftEntertainmentPolicy(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.usd = cls.env.ref('base.USD')
        cls.inr = cls.env.ref('base.INR')
        cls.usd.active = True
        cls.inr.active = True

    def _find(self, category, zone_xmlid, amount, currency):
        zone = self.env.ref(zone_xmlid)
        return self.env['bxi.gift.threshold']._find(
            category, zone, amount, currency, self.company, fields.Date.today()
        )[0]

    def test_india_giving_matrix(self):
        self.assertEqual(
            self._find('gift', 'bxi_gift_entertainment.zone_give_in', 500, self.inr)
            .step_ids.mapped('approver_type'), ['skip_manager'])
        self.assertEqual(
            self._find('gift', 'bxi_gift_entertainment.zone_give_in', 20000, self.inr)
            .step_ids.mapped('approver_type'), ['l4'])
        self.assertEqual(
            self._find('gift', 'bxi_gift_entertainment.zone_give_in', 45000, self.inr)
            .step_ids.mapped('approver_type'), ['l3'])
        self.assertEqual(
            self._find('gift', 'bxi_gift_entertainment.zone_give_in', 150000, self.inr)
            .step_ids.mapped('approver_type'), ['l2'])
        self.assertEqual(
            self._find('gift', 'bxi_gift_entertainment.zone_give_in', 600000, self.inr)
            .step_ids.mapped('approver_type'), ['l1'])
        self.assertEqual(
            self._find('gift', 'bxi_gift_entertainment.zone_give_in', 600000.01, self.inr)
            .step_ids.mapped('approver_type'), ['due_diligence', 'board'])

    def test_international_giving_matrix(self):
        self.assertEqual(
            self._find('gift', 'bxi_gift_entertainment.zone_give_global', 75, self.usd)
            .step_ids.mapped('approver_type'), ['skip_manager'])
        self.assertEqual(
            self._find('gift', 'bxi_gift_entertainment.zone_give_global', 75.01, self.usd)
            .step_ids.mapped('approver_type'), ['l4'])
        self.assertEqual(
            self._find('gift', 'bxi_gift_entertainment.zone_give_global', 15000, self.usd)
            .step_ids.mapped('approver_type'), ['l1'])
        self.assertEqual(
            self._find('gift', 'bxi_gift_entertainment.zone_give_global', 15000.01, self.usd)
            .step_ids.mapped('approver_type'), ['due_diligence', 'board'])

    def test_receiving_declaration_has_no_approval_step(self):
        for zone, amount in [
            ('bxi_gift_entertainment.zone_recv_aae', 150),
            ('bxi_gift_entertainment.zone_recv_row', 25),
        ]:
            row = self._find('receive', zone, amount, self.usd)
            self.assertEqual(row.outcome, 'declare')
            self.assertFalse(row.step_ids)

    def test_receiving_prohibited_limits(self):
        self.assertEqual(
            self._find('receive', 'bxi_gift_entertainment.zone_recv_aae', 200.01, self.usd).outcome,
            'prohibited')
        self.assertEqual(
            self._find('receive', 'bxi_gift_entertainment.zone_recv_row', 50.01, self.usd).outcome,
            'prohibited')

    def test_government_limit(self):
        row = self.env['bxi.gift.threshold']._find(
            'government', self.env.ref('bxi_gift_entertainment.zone_give_in'),
            50, self.usd, self.company, date.today())[0]
        self.assertEqual(row.outcome, 'approve')
        self.assertEqual(row.step_ids.mapped('approver_type'), ['l4'])
        row = self.env['bxi.gift.threshold']._find(
            'government', self.env.ref('bxi_gift_entertainment.zone_give_in'),
            50.01, self.usd, self.company, date.today())[0]
        self.assertEqual(row.outcome, 'prohibited')

    def test_donation_matrix(self):
        self.assertEqual(
            self._find('donation', 'bxi_gift_entertainment.zone_give_in', 10000, self.usd)
            .step_ids.mapped('approver_type'), ['l1', 'ethics_committee'])
        self.assertEqual(
            self._find('donation', 'bxi_gift_entertainment.zone_give_in', 10000.01, self.usd)
            .step_ids.mapped('approver_type'), ['ceo', 'cfo'])
        self.assertEqual(
            self._find('donation', 'bxi_gift_entertainment.zone_give_in', 250000.01, self.usd).outcome,
            'prohibited')
