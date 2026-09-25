# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import new_test_user, tagged
from odoo.tools import mute_logger

from .common import HdfcPayrollCommon


@tagged('post_install', '-at_install')
class TestHdfcMultiCompany(HdfcPayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls._create_company('HDFC Test Co B')
        cls.config_b = cls._create_config(cls.company_b, debit_account_number='50200099999999')
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=(cls.company | cls.company_b).ids))

    def test_one_batch_per_company(self):
        emp_a = self._create_employee('Mala', [('50100000000031', self.hdfc_bank, True)])
        emp_b = self._create_employee('Naveen', [('50100000000032', self.hdfc_bank, True)], company=self.company_b)
        slips = self._create_payslip(emp_a, 1000) | self._create_payslip(emp_b, 2000)
        batches = self._release(slips)
        self.assertEqual(len(batches), 2)
        by_company = {batch.company_id: batch for batch in batches}
        self.assertEqual(by_company[self.company].config_id, self.config)
        self.assertEqual(by_company[self.company_b].config_id, self.config_b)
        self.assertEqual(by_company[self.company_b].amount_total, 2000)

    def test_company_without_config(self):
        self.config_b.active = False
        emp_b = self._create_employee('Om', [('50100000000033', self.hdfc_bank, True)], company=self.company_b)
        _lines, errors = self._create_payslip(emp_b, 2000)._hdfc_prepare_payout()
        self.assertTrue(any('no active HDFC configuration' in e for e in errors))

    @mute_logger('odoo.sql_db')
    def test_single_active_config_per_company(self):
        with self.assertRaises(Exception), self.cr.savepoint():
            self.config.copy({'active': True})
            self.env.flush_all()

    def test_record_rules_isolate_companies(self):
        emp_b = self._create_employee('Pooja', [('50100000000034', self.hdfc_bank, True)], company=self.company_b)
        batch_b = self._release(self._create_payslip(emp_b, 2000))
        user_a = new_test_user(
            self.env, login='hdfc_manager_a', groups='bxi_hdfc_payroll.group_hdfc_payout_manager',
            company_id=self.company.id, company_ids=self.company.ids,
        )
        env_a = self.env(user=user_a, context=dict(self.env.context, allowed_company_ids=self.company.ids))
        self.assertNotIn(batch_b, env_a['hdfc.payout.batch'].search([]))
        with self.assertRaises(AccessError):
            batch_b.with_env(env_a).read(['name'])
