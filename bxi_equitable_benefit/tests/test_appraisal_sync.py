from datetime import date

from odoo.exceptions import UserError
from odoo.tests import new_test_user, tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestEquitableBenefitAppraisalSync(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Rate = cls.env['bxi.eb.rate']
        cls.employee = cls.env['hr.employee'].create({'name': 'EB Appraisal Employee'})
        cls.employee.version_id.write({'date_version': date(2025, 4, 1), 'eb_annual_component_a': 900000})
        cls.pattern_5 = cls.env.ref('bxi_equitable_benefit.work_pattern_5_day')
        cls.pattern_6 = cls.env.ref('bxi_equitable_benefit.work_pattern_6_day')
        cls.pattern_odd = cls.env.ref('bxi_equitable_benefit.work_pattern_odd_shift')
        cls.pattern_hybrid = cls.env.ref('bxi_equitable_benefit.work_pattern_hybrid')

    def _appraisal(self, **vals):
        return self.env['hr.employee.appraisal'].create(dict({
            'employee_id': self.employee.id,
            'letter_type': 'appraisal_letter',
            'appraisal_percentage': 10,
            'current_basic_salary': 50000,
            'effective_date': date(2026, 4, 1),
            'template_company_id': self.env.company.id,
        }, **vals))

    def _rate(self, pattern, category, deployment):
        return self.Rate._find_rate(pattern, category, deployment, date(2026, 4, 1), self.env.company)

    # Not Applicable rows -------------------------------------------------
    def test_not_applicable_combinations_seeded(self):
        self.assertEqual(self._rate(self.pattern_5, 'client', 'onsite').rate_percent, 0)
        self.assertTrue(self._rate(self.pattern_5, 'client', 'onsite'))
        self.assertEqual(self._rate(self.pattern_5, 'client', 'offshore').rate_percent, 5)
        self.assertTrue(self._rate(self.pattern_odd, 'non_client', 'onsite'))
        self.assertEqual(self._rate(self.pattern_odd, 'non_client', 'onsite').rate_percent, 0)
        self.assertEqual(self._rate(self.pattern_odd, 'client', 'onsite').rate_percent, 11)

    def test_not_applicable_rates_idempotent(self):
        count = self.Rate.with_context(active_test=False).search_count([])
        self.Rate._ensure_not_applicable_rates()
        self.assertEqual(self.Rate.with_context(active_test=False).search_count([]), count)

    # Documentation of non-client patterns --------------------------------
    def test_non_client_paying_pattern_needs_objective(self):
        assignment = self.env['bxi.eb.assignment'].create({
            'employee_id': self.employee.id,
            'date_from': date(2026, 4, 1),
            'work_category': 'non_client',
            'deployment': 'offshore',
            'work_pattern_id': self.pattern_6.id,
        })
        with self.assertRaises(UserError):
            assignment.action_submit()
        assignment.project_ids = self.env['project.project'].create({'name': 'Internal platform migration'})
        assignment.action_submit()
        self.assertEqual(assignment.state, 'submitted')

    def test_client_from_project_customer(self):
        customer = self.env['res.partner'].create({'name': 'EB Client Ltd', 'is_company': True})
        project = self.env['project.project'].create({'name': 'EB Client Project', 'partner_id': customer.id})
        internal = self.env['project.project'].create({'name': 'EB Internal Project'})
        assignment = self.env['bxi.eb.assignment'].create({
            'employee_id': self.employee.id,
            'date_from': date(2026, 4, 1),
            'work_category': 'client',
            'deployment': 'offshore',
            'work_pattern_id': self.pattern_6.id,
            'project_ids': [(6, 0, internal.ids)],
        })
        self.assertFalse(assignment.client_id)
        assignment.project_ids |= project
        self.assertEqual(assignment.client_id, customer)
        assignment.project_ids = internal
        self.assertFalse(assignment.client_id)

    def test_non_client_not_applicable_pattern_needs_no_objective(self):
        assignment = self.env['bxi.eb.assignment'].create({
            'employee_id': self.employee.id,
            'date_from': date(2026, 4, 1),
            'work_category': 'non_client',
            'deployment': 'offshore',
            'work_pattern_id': self.pattern_hybrid.id,
        })
        assignment.action_submit()
        self.assertEqual(assignment.state, 'submitted')

    # Appraisal -> rating and Component A ---------------------------------
    def test_release_syncs_rating(self):
        appraisal = self._appraisal(eb_rating='exceeds')
        self.assertEqual(appraisal.eb_rating_fy_start, date(2025, 4, 1))
        appraisal.state = 'released'
        rating = self.env['bxi.eb.performance.rating'].search([('employee_id', '=', self.employee.id)])
        self.assertEqual(len(rating), 1)
        self.assertEqual((rating.fy_start, rating.rating, rating.appraisal_id), (date(2025, 4, 1), 'exceeds', appraisal))
        appraisal.eb_rating = 'meets'
        self.assertEqual(rating.rating, 'meets')

    def test_release_overwrites_manual_rating(self):
        rating = self.env['bxi.eb.performance.rating'].create({
            'employee_id': self.employee.id, 'fy_start': date(2025, 4, 1), 'rating': 'below',
        })
        self._appraisal(eb_rating='outstanding').state = 'released'
        self.assertEqual(rating.rating, 'outstanding')

    def test_release_sets_component_a_from_effective_date(self):
        carried = self.employee.create_version({'date_version': date(2026, 6, 1)})
        changed = self.employee.create_version({'date_version': date(2026, 8, 1)})
        changed.eb_annual_component_a = 1500000
        appraisal = self._appraisal()
        # (50000 basic + 10%) * 1.7 (flexible allowance) * 12
        self.assertAlmostEqual(appraisal.annual_fixed, 1122000)
        appraisal.state = 'released'
        self.assertEqual(self.employee._get_version(date(2026, 3, 31)).eb_annual_component_a, 900000)
        self.assertEqual(self.employee._get_version(date(2026, 4, 1)).eb_annual_component_a, 1122000)
        self.assertEqual(carried.eb_annual_component_a, 1122000)
        self.assertEqual(changed.eb_annual_component_a, 1500000)

    def test_bonus_letter_keeps_component_a(self):
        self._appraisal(letter_type='bonus_letter', bonus_amount=10000, eb_rating='meets').state = 'released'
        self.assertEqual(self.employee._get_version(date(2026, 4, 1)).eb_annual_component_a, 900000)
        self.assertTrue(self.env['bxi.eb.performance.rating'].search([('employee_id', '=', self.employee.id)]))

    def test_draft_appraisal_changes_nothing(self):
        self._appraisal(eb_rating='exceeds')
        self.assertFalse(self.env['bxi.eb.performance.rating'].search([('employee_id', '=', self.employee.id)]))
        self.assertEqual(self.employee._get_version(date(2026, 4, 1)).eb_annual_component_a, 900000)

    # Fill Component A wizard ---------------------------------------------
    def test_wizard_proposes_and_fills_missing_component_a(self):
        employee = self.env['hr.employee'].create({'name': 'EB Missing Component A',
                                                   'l10n_in_basic_salary_amount': 40000})
        self.env['bxi.eb.assignment'].create({
            'employee_id': employee.id,
            'date_from': date(2026, 4, 1),
            'work_category': 'client',
            'deployment': 'offshore',
            'work_pattern_id': self.pattern_6.id,
            'justification': 'Client requires Saturday support',
            'state': 'approved',
        })
        hr_user = new_test_user(self.env, login='eb_hr_officer', groups='base.group_user,hr.group_hr_user')
        wizard = self.env['bxi.eb.component.a.wizard'].with_user(hr_user).create({})
        line = wizard.line_ids.filtered(lambda l: l.employee_id == employee)
        self.assertEqual(line.proposed_amount, 816000)
        self.assertTrue(line.apply)
        self.assertNotIn(self.employee, wizard.line_ids.employee_id, "Only employees with approved patterns")
        wizard.line_ids.filtered(lambda l: l.employee_id != employee).apply = False
        wizard.action_apply()
        self.assertEqual(employee.version_id.eb_annual_component_a, 816000)

    def test_wizard_prefers_released_appraisal(self):
        self._appraisal().state = 'released'
        amount, _source = self.env['bxi.eb.component.a.wizard']._propose(self.employee)
        self.assertAlmostEqual(amount, 1122000)

    def test_wizard_requires_hr_rights(self):
        user = new_test_user(self.env, login='eb_plain_user', groups='base.group_user')
        wizard = self.env['bxi.eb.component.a.wizard'].create({'line_ids': [(0, 0, {
            'employee_id': self.employee.id, 'proposed_amount': 1, 'apply': True})]})
        with self.assertRaises(UserError):
            wizard.with_user(user).action_apply()
