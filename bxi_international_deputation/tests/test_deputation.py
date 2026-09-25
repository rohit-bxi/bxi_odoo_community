import re
from datetime import date, datetime

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestDeputation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.country_id = cls.env.ref('base.in')
        cls.uk = cls.env.ref('base.uk')
        cls.germany = cls.env.ref('base.de')
        cls.gbp = cls.env.ref('base.GBP')
        cls.officer = new_test_user(
            cls.env, login='dep_officer',
            groups='base.group_user,hr.group_hr_user,bxi_international_deputation.group_deputation_officer')
        cls.employee_user = new_test_user(cls.env, login='dep_employee', groups='base.group_user')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Aarav',
            'user_id': cls.employee_user.id,
            'work_email': 'aarav@example.com',
            'date_version': date(2020, 1, 1),
            'l10n_in_basic_salary_amount': 20000,
            'l10n_in_hra': 8000,
            'l10n_in_fixed_allowance': 3000,
        })

    def _deputation(self, country=None, arrival=date(2026, 5, 2), gross=52000.0):
        deputation = self.env['bxi.deputation'].with_user(self.officer).create({
            'employee_id': self.employee.id,
            'host_country_id': (country or self.uk).id,
            'planned_start_date': arrival,
            'host_currency_id': self.gbp.id,
            'host_annual_gross': gross,
        })
        deputation.action_approve()
        deputation.arrival_date = arrival
        return deputation

    def test_uk_rule_is_working_days(self):
        deputation = self._deputation()
        self.assertEqual(deputation.rule_id, self.env.ref('bxi_international_deputation.rule_uk'))
        self.assertEqual(deputation.salary_approach, 'working')
        self.assertEqual(deputation.host_calendar_id, self.env.ref('bxi_international_deputation.calendar_host_uk'))

    def test_outbound_saturday_arrival_uk(self):
        """India -> UK on Saturday 2 May 2026: Sunday is a gap day paid as 52000 / 260 = 200."""
        deputation = self._deputation()
        self.assertEqual(deputation.home_last_date, date(2026, 5, 2))
        self.assertEqual(deputation.host_start_date, date(2026, 5, 4))
        self.assertEqual(deputation.outbound_gap_days, 1)
        self.assertAlmostEqual(deputation.gap_day_rate, 200.0)
        self.assertAlmostEqual(deputation.outbound_gap_amount, 200.0)

    def test_host_public_holiday_is_gap_day(self):
        """The UK bank holiday on Monday 4 May 2026 makes Monday a gap day too."""
        self.env['resource.calendar.leaves'].create({
            'name': 'Early May bank holiday',
            'calendar_id': self.env.ref('bxi_international_deputation.calendar_host_uk').id,
            'date_from': datetime(2026, 5, 4, 0, 0),
            'date_to': datetime(2026, 5, 4, 22, 0),
        })
        deputation = self._deputation()
        self.assertEqual(deputation.host_start_date, date(2026, 5, 5))
        self.assertEqual(deputation.outbound_gap_days, 2)
        self.assertAlmostEqual(deputation.outbound_gap_amount, 400.0)

    def test_calendar_days_country(self):
        """Germany is not on the list: the host salary starts on the arrival date, no gap."""
        deputation = self._deputation(country=self.germany)
        self.assertFalse(deputation.rule_id)
        self.assertEqual(deputation.salary_approach, 'calendar')
        self.assertEqual(deputation.home_last_date, date(2026, 5, 1))
        self.assertEqual(deputation.host_start_date, date(2026, 5, 2))
        self.assertEqual(deputation.outbound_gap_days, 0)

    def test_effective_date_rule(self):
        """An older Calendar Days rule applies to arrivals before the Working Days rule starts."""
        Rule = self.env['bxi.deputation.country.rule']
        singapore = self.env.ref('base.sg')
        self.env.ref('bxi_international_deputation.rule_sg').effective_from = date(2026, 6, 1)
        Rule.create({'country_id': singapore.id, 'salary_approach': 'calendar'})
        self.assertEqual(Rule._get_rule(singapore, date(2026, 5, 20)).salary_approach, 'calendar')
        self.assertEqual(Rule._get_rule(singapore, date(2026, 6, 1)).salary_approach, 'working')

    def test_transfer_and_return(self):
        deputation = self._deputation()
        deputation.with_user(self.officer).action_confirm_arrival()
        self.assertEqual(deputation.state, 'transferred')
        self.assertTrue(self.employee.is_on_deputation)
        self.assertEqual(self.employee.deputation_country_id, self.uk)
        self.assertEqual(self.employee.onsite_offshore, 'onsite')
        self.assertTrue(deputation.letter_sent)

        with self.assertRaises(UserError):
            deputation.with_user(self.officer).arrival_date = date(2026, 5, 6)

        # UK -> India, landing on Sunday 13 Sep 2026.
        deputation.with_user(self.officer).return_landing_date = date(2026, 9, 13)
        self.assertEqual(deputation.host_last_date, date(2026, 9, 11))
        self.assertEqual(deputation.home_restart_date, date(2026, 9, 13))
        self.assertEqual(deputation.return_gap_days, 1)
        deputation.with_user(self.officer).action_confirm_return()
        self.assertEqual(deputation.state, 'returned')
        self.assertFalse(self.employee.is_on_deputation)

    def test_gross_required_when_gap(self):
        deputation = self._deputation(gross=0.0)
        with self.assertRaises(UserError):
            deputation.with_user(self.officer).action_confirm_arrival()

    def test_single_active_deputation(self):
        self._deputation()
        with self.assertRaises(ValidationError):
            self._deputation(country=self.germany)

    def test_employee_sees_only_own(self):
        deputation = self._deputation()
        other = self.env['hr.employee'].create({'name': 'Other', 'date_version': date(2020, 1, 1)})
        other_deputation = self.env['bxi.deputation'].create({
            'employee_id': other.id, 'host_country_id': self.uk.id, 'planned_start_date': date(2026, 5, 2)})
        visible = self.env['bxi.deputation'].with_user(self.employee_user).search([])
        self.assertIn(deputation, visible)
        self.assertNotIn(other_deputation, visible)

    def test_off_home_payroll_days(self):
        deputation = self._deputation()
        deputation.action_confirm_arrival()
        # India pays 1-2 May; 3-31 May is on the UK payroll.
        self.assertEqual(self.employee._get_off_home_payroll_days(date(2026, 5, 1), date(2026, 5, 31)), 29)
        self.assertEqual(self.employee._get_off_home_payroll_days(date(2026, 6, 1), date(2026, 6, 30)), 30)
        self.assertEqual(self.employee._get_off_home_payroll_days(date(2026, 4, 1), date(2026, 4, 30)), 0)
        deputation.return_landing_date = date(2026, 9, 13)
        deputation.action_confirm_return()
        # India restarts on 13 Sep: 1-12 Sep are off the home payroll.
        self.assertEqual(self.employee._get_off_home_payroll_days(date(2026, 9, 1), date(2026, 9, 30)), 12)

    def test_payslip_proration(self):
        deputation = self._deputation()
        deputation.action_confirm_arrival()
        structure = self.env.ref('custom_payslip_report.structure_india_regular_pay')
        self.assertIn(self.env.ref('bxi_international_deputation.hr_rule_deputation_nopay'), structure.rule_ids)
        slip = self.env['hr.payslip'].create({
            'name': 'May 2026',
            'employee_id': self.employee.id,
            'version_id': self.employee.version_id.id,
            'struct_id': structure.id,
            'date_from': date(2026, 5, 1),
            'date_to': date(2026, 5, 31),
        })
        slip._sync_deputation_input()
        inputs = {line.code: line.amount for line in slip.input_line_ids}
        # Fixed pay 31000 (Basic 20000) x 29 / 31 days on the UK payroll.
        self.assertAlmostEqual(inputs['DEP_NOPAY'], 29000.0)
        self.assertAlmostEqual(inputs['DEP_NOPAY_BASIC'], 18709.68)

        # Some rules of custom_payslip_report test inputs with "'X' in inputs",
        # which InputLine does not support; use the attribute form here.
        for rule in self.env['hr.salary.rule'].search([('amount_python_compute', 'like', ' in inputs')]):
            rule.amount_python_compute = re.sub(r"'(\w+)' in inputs", r"inputs.\1", rule.amount_python_compute)
        slip.compute_sheet()
        totals = {line.code: line.total for line in slip.line_ids}
        self.assertAlmostEqual(totals['GROSS'], 2000.0)
        self.assertAlmostEqual(totals['PT'], 0.0)
        self.assertAlmostEqual(totals['PF'] + totals['DEP_PF_ADJ'], -154.84)
        self.assertAlmostEqual(totals['NET'], 1845.16)

        june = self.env['hr.payslip'].create({
            'name': 'June 2026',
            'employee_id': self.employee.id,
            'version_id': self.employee.version_id.id,
            'struct_id': structure.id,
            'date_from': date(2026, 6, 1),
            'date_to': date(2026, 6, 30),
        })
        with self.assertRaises(UserError):
            june._sync_deputation_input()

    def test_attendance_geofence_skipped(self):
        deputation = self._deputation()
        deputation.action_confirm_arrival()
        # No GPS and no work location: would raise for an employee in India.
        self.env['hr.attendance']._validate_location_access({
            'employee_id': self.employee.id, 'check_in': datetime(2026, 5, 6, 9, 0)})
