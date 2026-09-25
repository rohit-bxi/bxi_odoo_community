from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CertificationCommon


@tagged('post_install', '-at_install')
class TestHrEmployee(CertificationCommon):

    def test_parse_band_level(self):
        parse = self.env['hr.employee']._parse_band_level
        self.assertEqual(parse('4.1'), 4)
        self.assertEqual(parse('10'), 10)
        self.assertEqual(parse('0'), 0)
        self.assertEqual(parse(' 6.2 '), 6)
        self.assertIsNone(parse(False))
        self.assertIsNone(parse(''))
        self.assertIsNone(parse('None'))

    def test_band_level_compute(self):
        self.assertEqual(self.band4.band_level, 4)
        self.assertTrue(self.band4.is_band_set)
        self.assertFalse(self.ceo.is_band_set)
        self.engineer.role_band = '0'
        self.assertTrue(self.engineer.is_band_set)
        self.assertEqual(self.engineer.band_level, 0)
        self.engineer.role_band = False
        self.assertFalse(self.engineer.is_band_set)

    def test_is_india_payroll_follows_company_country(self):
        self.assertTrue(self.engineer.is_india_payroll)
        company = self.env['res.company'].create({'name': 'Dubai Co', 'country_id': self.env.ref('base.ae').id})
        employee = self.env['hr.employee'].create({'name': 'Dubai Employee', 'company_id': company.id})
        self.assertFalse(employee.is_india_payroll)
        employee.is_india_payroll = True
        self.assertTrue(employee.is_india_payroll)

    def test_has_active_resignation(self):
        self.assertFalse(self.engineer.has_active_resignation)
        resignation = self._resign(self.engineer, submit=False)
        self.engineer.invalidate_recordset(['has_active_resignation'])
        self.assertFalse(self.engineer.has_active_resignation, "A draft resignation does not count")
        resignation.action_submit()
        self.engineer.invalidate_recordset(['has_active_resignation'])
        self.assertTrue(self.engineer.has_active_resignation)
        resignation.action_approve()
        self.engineer.invalidate_recordset(['has_active_resignation'])
        self.assertTrue(self.engineer.has_active_resignation)

    def test_exact_band_head(self):
        self.assertEqual(self.engineer._get_band_head(4), self.band4)
        self.assertEqual(self.engineer._get_band_head(3), self.band3)
        self.assertEqual(self.engineer._get_band_head(2), self.band2)

    def test_band_head_falls_back_to_more_senior_band(self):
        self.manager.parent_id = self.band3
        self.assertEqual(self.engineer._get_band_head(2), self.band3)

    def test_band_head_falls_back_to_head_of_reporting_line(self):
        self.assertEqual(self.engineer._get_band_head(6), self.ceo)

    def test_band_head_ignores_unbanded_managers_in_between(self):
        self.manager.role_band = False
        self.assertEqual(self.engineer._get_band_head(2), self.band2)

    def test_employee_is_not_own_band_head(self):
        self.assertEqual(self.band4._get_band_head(4), self.ceo)

    def test_missing_band_head(self):
        top = self.env['hr.employee'].create({'name': 'Top', 'role_band': '2.1'})
        junior = self.env['hr.employee'].create({'name': 'Junior', 'role_band': '1.1', 'parent_id': top.id})
        with self.assertRaises(UserError):
            junior._get_band_head(4)
        self.assertFalse(junior._get_band_head(4, raise_if_not_found=False))
        self.assertFalse(self.ceo._get_band_head(4, raise_if_not_found=False))

    def test_skip_manager(self):
        self.assertEqual(self.engineer._get_skip_manager(), self.band2)
        self.assertEqual(self.band4._get_skip_manager(), self.ceo)
        self.assertFalse(self.ceo._get_skip_manager())
