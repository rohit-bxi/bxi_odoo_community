import re
from datetime import date, datetime

from freezegun import freeze_time

from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, TransactionCase, new_test_user, tagged


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
        cls.manager = new_test_user(
            cls.env, login='dep_manager',
            groups='base.group_user,hr.group_hr_user,bxi_international_deputation.group_deputation_manager')
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

    def _home_slip(self, date_from, date_to, done=False):
        slip = self.env['hr.payslip'].create({
            'name': 'Home %s' % date_from,
            'employee_id': self.employee.id,
            'version_id': self.employee.version_id.id,
            'struct_id': self.env.ref('custom_payslip_report.structure_india_regular_pay').id,
            'date_from': date_from,
            'date_to': date_to,
        })
        slip._sync_deputation_input()
        if done:
            slip.state = 'done'
        return slip

    def _patch_input_rules(self):
        # Some rules of custom_payslip_report test inputs with "'X' in inputs",
        # which InputLine does not support; use the attribute form here.
        for rule in self.env['hr.salary.rule'].search([('amount_python_compute', 'like', ' in inputs')]):
            rule.amount_python_compute = re.sub(r"'(\w+)' in inputs", r"inputs.\1", rule.amount_python_compute)

    def _inputs(self, slip):
        return {line.code: line.amount for line in slip.input_line_ids}

    def test_tds_prorated(self):
        """The TDS share of the days on the host payroll is refunded: 3100 x 29 / 31."""
        self.employee.l10n_in_tds = 3100
        self._deputation().action_confirm_arrival()
        slip = self._home_slip(date(2026, 5, 1), date(2026, 5, 31))
        self.assertAlmostEqual(self._inputs(slip)['DEP_TDS_ADJ'], 2900.0)

    def test_late_arrival_recovered_on_next_payslip(self):
        """May was paid in full before the arrival on 2 May was confirmed: the 29 days on the UK
        payroll are recovered with the September payslip, TDS included."""
        self.employee.l10n_in_tds = 3100
        deputation = self._deputation()
        may = self._home_slip(date(2026, 5, 1), date(2026, 5, 31), done=True)
        self.assertFalse(self._inputs(may).get('DEP_NOPAY'))
        deputation.action_confirm_arrival()
        self.assertIn('29 day(s) to recover', ''.join(deputation.message_ids.mapped('body')))
        deputation.return_landing_date = date(2026, 9, 13)
        deputation.action_confirm_return()

        september = self._home_slip(date(2026, 9, 1), date(2026, 9, 30))
        inputs = self._inputs(september)
        self.assertEqual(september.dep_retro_line_ids.source_payslip_id, may)
        self.assertEqual(september.dep_retro_line_ids.days, 29)
        self.assertAlmostEqual(inputs['DEP_RETRO'], 29000.0)
        self.assertAlmostEqual(inputs['DEP_RETRO_BASIC'], 18709.68)
        # 12 September days on the UK payroll (3100 x 12 / 30) plus May's 29 days (100 a day).
        self.assertAlmostEqual(inputs['DEP_TDS_ADJ'], 1240.0 + 2900.0)

        self._patch_input_rules()
        september.action_payslip_done()
        self.assertEqual(may.dep_settled_days, 29)
        october = self._home_slip(date(2026, 10, 1), date(2026, 10, 31))
        self.assertFalse(october.dep_retro_line_ids)
        self.assertFalse(self._inputs(october).get('DEP_RETRO'))

        september.action_payslip_cancel()
        self.assertEqual(may.dep_settled_days, 0)

    def test_corrected_arrival_pays_back(self):
        """A later arrival date than the one May was paid on gives the withheld days back."""
        deputation = self._deputation()
        deputation.action_confirm_arrival()
        may = self._home_slip(date(2026, 5, 1), date(2026, 5, 31), done=True)
        self.assertEqual(may.dep_settled_days, 29)
        # Corrected by a manager: the employee landed on Saturday 9 May, UK payroll from Monday 11.
        deputation.with_user(self.manager).arrival_date = date(2026, 5, 9)
        deputation.return_landing_date = date(2026, 9, 13)
        deputation.action_confirm_return()
        september = self._home_slip(date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(september.dep_retro_line_ids.days, -7)
        self.assertAlmostEqual(self._inputs(september)['DEP_RETRO'], -7000.0)

    def test_untracked_payslips_left_alone(self):
        """Payslips confirmed before the tracking existed are never corrected."""
        deputation = self._deputation()
        may = self._home_slip(date(2026, 5, 1), date(2026, 5, 31), done=True)
        may.dep_tracked = False
        deputation.action_confirm_arrival()
        deputation.return_landing_date = date(2026, 9, 13)
        deputation.action_confirm_return()
        self.assertFalse(self._home_slip(date(2026, 9, 1), date(2026, 9, 30)).dep_retro_line_ids)

    @freeze_time('2026-06-15')
    def test_tax_residency_review(self):
        deputation = self._deputation()
        deputation.planned_end_date = date(2026, 8, 31)
        deputation.action_confirm_arrival()
        # 2 May - 31 Aug: 122 days abroad, still 182 days possible in India.
        self.assertEqual(deputation.fy_days_abroad, 122)
        self.assertFalse(deputation.residency_review)
        deputation.planned_end_date = date(2027, 3, 31)
        # 2 May 2026 - 31 Mar 2027: 334 days abroad.
        self.assertEqual(deputation.fy_days_abroad, 334)
        self.assertTrue(deputation.residency_review)
        self.env['bxi.deputation']._cron_deputation_reminders()
        self.assertIn('Deputation: review tax residency', deputation.activity_ids.mapped('summary'))

    def test_attendance_geofence_skipped(self):
        deputation = self._deputation()
        deputation.action_confirm_arrival()
        # No GPS and no work location: would raise for an employee in India.
        self.env['hr.attendance']._validate_location_access({
            'employee_id': self.employee.id, 'check_in': datetime(2026, 5, 6, 9, 0)})

    def test_host_states_follow_country(self):
        us = self.env.ref('base.us')
        georgia, texas = self.env.ref('base.state_us_11'), self.env.ref('base.state_us_44')
        form = Form(self.env['bxi.deputation'].with_user(self.officer))
        form.employee_id = self.employee
        form.host_country_id = us
        form.host_state_ids.add(georgia)
        form.host_state_ids.add(texas)
        form.host_city = 'Atlanta'
        # Changing the country drops the states of the previous country
        form.host_country_id = self.uk
        self.assertFalse(form.host_state_ids)
        form.host_country_id = us
        form.host_state_ids.add(georgia)
        form.planned_start_date = date(2026, 5, 2)
        deputation = form.save()
        self.assertEqual(deputation.host_state_ids, georgia)
        self.assertEqual(deputation.host_city, 'Atlanta')

    def test_travel_request_fills_host_details_and_project(self):
        us, georgia = self.env.ref('base.us'), self.env.ref('base.state_us_11')
        project = self.env['project.project'].create({'name': 'Acme Rollout'})
        request = self.env['travel.request'].create({
            'employee_id': self.employee.id, 'travel_purpose': 'Deputation',
            'from_country': self.env.ref('base.in').id, 'from_city': 'Pune',
            'to_country': us.id, 'to_state': georgia.id, 'to_city': 'Atlanta',
            'departure_date': date(2026, 5, 2), 'project_id': project.id,
        })
        form = Form(self.env['bxi.deputation'])
        form.employee_id = self.employee
        form.travel_request_id = request
        self.assertEqual(form.host_country_id, us)
        self.assertEqual(form.host_state_ids[:], georgia)
        self.assertEqual(form.host_city, 'Atlanta')
        self.assertEqual(form.project_id, project)
        self.assertEqual(form.planned_start_date, date(2026, 5, 2))
