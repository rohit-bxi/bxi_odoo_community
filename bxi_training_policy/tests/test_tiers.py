from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import TrainingCommon


@tagged('post_install', '-at_install')
class TestAgreementTiers(TrainingCommon):

    def test_policy_boundaries(self):
        Tier = self.env['bxi.training.agreement.tier']
        expected = {
            29999: 0, 30000: 12, 49999.99: 12, 50000: 12, 99999: 12, 99999.99: 12, 100000: 24, 500000: 24,
        }
        for amount, months in expected.items():
            self.assertEqual(Tier._get_tier(amount, self.company).months or 0, months, amount)

    def test_overlap_rejected(self):
        with self.assertRaises(ValidationError):
            self.env['bxi.training.agreement.tier'].create({'min_amount': 90000, 'max_amount': 150000, 'months': 18})

    def test_company_tiers_replace_shared_ones(self):
        Tier = self.env['bxi.training.agreement.tier']
        Tier.create({'min_amount': 10000, 'max_amount': 0, 'months': 6, 'company_id': self.company.id})
        self.assertEqual(Tier._get_tier(20000, self.company).months, 6)
        self.assertEqual(Tier._get_tier(200000, self.company).months, 6)

    def test_agreement_required_from_threshold(self):
        below = self._new_training(fee=20000, lodging=9999)
        at = self._new_training(fee=20000, lodging=10000)
        self.assertFalse(below.agreement_required)
        self.assertTrue(at.agreement_required)
