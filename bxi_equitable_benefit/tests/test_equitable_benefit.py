from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestEquitableBenefit(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        set_param = cls.env['ir.config_parameter'].sudo().set_param
        set_param('bxi_equitable_benefit.fy_start_month', 4)
        set_param('bxi_equitable_benefit.proration_basis', 'months')
        set_param('bxi_equitable_benefit.min_rating', 'meets')
        set_param('bxi_equitable_benefit.allow_missing_rating', False)
        set_param('bxi_equitable_benefit.max_unauthorized_days', 3)
        set_param('bxi_equitable_benefit.unpaid_leave_threshold_days', 30)

        cls.reviewer = new_test_user(
            cls.env, login='eb_reviewer', groups='base.group_user,bxi_equitable_benefit.group_eb_revenue_assurance')
        cls.finance = new_test_user(
            cls.env, login='eb_finance', groups='base.group_user,bxi_equitable_benefit.group_eb_finance')
        cls.employee_user = new_test_user(cls.env, login='eb_employee', groups='base.group_user')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Riya',
            'user_id': cls.employee_user.id,
            'date_version': date(2020, 1, 1),
        })
        cls.employee.eb_annual_component_a = 600000

        cls.pattern_hybrid = cls.env.ref('bxi_equitable_benefit.work_pattern_hybrid')
        cls.pattern_5 = cls.env.ref('bxi_equitable_benefit.work_pattern_5_day')
        cls.pattern_6 = cls.env.ref('bxi_equitable_benefit.work_pattern_6_day')
        cls.pattern_odd = cls.env.ref('bxi_equitable_benefit.work_pattern_odd_shift')
        cls.fy_start, cls.fy_end = date(2025, 4, 1), date(2026, 3, 31)
        cls.rating = cls.env['bxi.eb.performance.rating'].create({
            'employee_id': cls.employee.id, 'fy_start': cls.fy_start, 'rating': 'meets'})

    def _assignment(self, pattern, date_from, date_to=None, category='client', deployment='offshore', employee=None):
        assignment = self.env['bxi.eb.assignment'].create({
            'employee_id': (employee or self.employee).id,
            'date_from': date_from,
            'date_to': date_to,
            'work_pattern_id': pattern.id,
            'work_category': category,
            'deployment': deployment,
            'justification': 'Client SOW requires this schedule',
        })
        assignment.action_submit()
        assignment.with_user(self.reviewer).action_approve()
        return assignment

    def _payout(self, period_end=None, employee=None):
        payout = self.env['bxi.eb.payout'].create({
            'employee_id': (employee or self.employee).id,
            'fy_start': self.fy_start,
            'fy_end': self.fy_end,
            'period_end': period_end or self.fy_end,
        })
        payout.with_user(self.reviewer).action_compute()
        return payout

    # ------------------------------------------------------------------
    # Rate matrix
    # ------------------------------------------------------------------
    def test_seeded_matrix(self):
        Rate = self.env['bxi.eb.rate']
        company = self.env.company
        day = date(2025, 6, 1)
        self.assertEqual(Rate._find_rate(self.pattern_hybrid, 'non_client', 'onsite', day, company).rate_percent, 0)
        self.assertEqual(Rate._find_rate(self.pattern_5, 'client', 'offshore', day, company).rate_percent, 5)
        self.assertFalse(Rate._find_rate(self.pattern_5, 'client', 'onsite', day, company))
        self.assertEqual(Rate._find_rate(self.pattern_6, 'non_client', 'onsite', day, company).rate_percent, 9.6)
        self.assertEqual(Rate._find_rate(self.pattern_odd, 'client', 'onsite', day, company).rate_percent, 11)
        self.assertFalse(Rate._find_rate(self.pattern_odd, 'non_client', 'onsite', day, company))

    def test_specific_rate_wins(self):
        self.env['bxi.eb.rate'].create({
            'work_pattern_id': self.pattern_6.id, 'work_category': 'client', 'deployment': 'onsite',
            'rate_percent': 10.33})
        rate = self.env['bxi.eb.rate']._find_rate(self.pattern_6, 'client', 'onsite', date(2025, 6, 1),
                                                  self.env.company)
        self.assertEqual(rate.rate_percent, 10.33)

    def test_rate_overlap_rejected(self):
        with self.assertRaises(ValidationError):
            self.env['bxi.eb.rate'].create({
                'work_pattern_id': self.pattern_6.id, 'work_category': 'any', 'deployment': 'any',
                'rate_percent': 12})

    # ------------------------------------------------------------------
    # Assignments
    # ------------------------------------------------------------------
    def test_submit_without_rate(self):
        assignment = self.env['bxi.eb.assignment'].create({
            'employee_id': self.employee.id, 'date_from': self.fy_start, 'work_pattern_id': self.pattern_odd.id,
            'work_category': 'non_client', 'deployment': 'onsite'})
        with self.assertRaises(UserError):
            assignment.action_submit()

    def test_client_aligned_requires_documentation(self):
        assignment = self.env['bxi.eb.assignment'].create({
            'employee_id': self.employee.id, 'date_from': self.fy_start, 'work_pattern_id': self.pattern_6.id,
            'work_category': 'client', 'deployment': 'onsite'})
        with self.assertRaises(UserError):
            assignment.action_submit()

    def test_overlap_rejected(self):
        self._assignment(self.pattern_6, self.fy_start, date(2025, 9, 30))
        with self.assertRaises(ValidationError):
            self._assignment(self.pattern_5, date(2025, 9, 1))

    def test_employee_cannot_approve_or_edit(self):
        assignment = self.env['bxi.eb.assignment'].with_user(self.employee_user).create({
            'employee_id': self.employee.id, 'date_from': self.fy_start, 'work_pattern_id': self.pattern_6.id,
            'work_category': 'non_client', 'deployment': 'onsite'})
        assignment.action_submit()
        with self.assertRaises(UserError):
            assignment.action_approve()
        with self.assertRaises(UserError):
            assignment.write({'client_name': 'Other'})

    # ------------------------------------------------------------------
    # Computation (policy illustrative examples)
    # ------------------------------------------------------------------
    def test_full_year_six_day(self):
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        payout = self._payout()
        self.assertTrue(payout.is_eligible)
        self.assertAlmostEqual(payout.amount_final, 57600)

    def test_odd_shift_full_year(self):
        self.employee.eb_annual_component_a = 480000
        self._assignment(self.pattern_odd, self.fy_start)
        self.assertAlmostEqual(self._payout().amount_final, 52800)

    def test_pattern_change_during_year(self):
        self._assignment(self.pattern_5, self.fy_start, date(2025, 9, 30))
        self._assignment(self.pattern_6, date(2025, 10, 1))
        payout = self._payout()
        self.assertEqual(len(payout.line_ids), 2)
        # 3,00,000 x 5% + 3,00,000 x 9.6%
        self.assertAlmostEqual(payout.amount_final, 15000 + 28800)

    def test_hybrid_not_applicable(self):
        self._assignment(self.pattern_hybrid, self.fy_start, category='non_client')
        payout = self._payout()
        self.assertTrue(payout.is_eligible)
        self.assertEqual(payout.amount_final, 0)

    def test_separation_fnf(self):
        """Example 5 with the exact 8/12 share: 6,00,000 x 10.33% x 8/12."""
        self.env['bxi.eb.rate'].create({
            'work_pattern_id': self.pattern_6.id, 'work_category': 'client', 'deployment': 'onsite',
            'rate_percent': 10.33})
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        payout = self.env['bxi.eb.payout']._create_fnf_payout(self.employee, date(2025, 11, 30))
        self.assertEqual(payout.payout_type, 'fnf')
        self.assertEqual(payout.period_end, date(2025, 11, 30))
        self.assertAlmostEqual(payout.amount_final, 41320)

    def test_days_basis(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_equitable_benefit.proration_basis', 'days')
        self._assignment(self.pattern_6, self.fy_start, date(2025, 4, 30), deployment='onsite')
        self.assertAlmostEqual(self._payout().amount_final, round(600000 * 0.096 * 30 / 365, 2))

    def test_component_a_change(self):
        self.employee.create_version({'date_version': date(2025, 10, 1), 'eb_annual_component_a': 1200000})
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        payout = self._payout()
        self.assertEqual(len(payout.line_ids), 2)
        self.assertAlmostEqual(payout.amount_final, 28800 + 57600)

    def test_rate_revision_mid_year(self):
        self.env.ref('bxi_equitable_benefit.rate_6_day').date_to = date(2025, 9, 30)
        self.env['bxi.eb.rate'].create({
            'work_pattern_id': self.pattern_6.id, 'work_category': 'any', 'deployment': 'any',
            'rate_percent': 12, 'date_from': date(2025, 10, 1)})
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        self.assertAlmostEqual(self._payout().amount_final, 28800 + 36000)

    # ------------------------------------------------------------------
    # Eligibility
    # ------------------------------------------------------------------
    def test_disciplinary_action_blocks(self):
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        self.env['bxi.eb.disciplinary.action'].create({
            'employee_id': self.employee.id, 'name': 'Warning', 'date_from': date(2025, 5, 1)})
        payout = self._payout()
        self.assertFalse(payout.is_eligible)
        self.assertEqual(payout.amount_final, 0)

    def test_rating_below_expectations(self):
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        self.rating.rating = 'below'
        self.assertFalse(self._payout().is_eligible)

    def test_missing_rating(self):
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        self.rating.unlink()
        self.assertFalse(self._payout().is_eligible)
        self.env['ir.config_parameter'].sudo().set_param('bxi_equitable_benefit.allow_missing_rating', True)
        payout = self.env['bxi.eb.payout'].search([('employee_id', '=', self.employee.id)])
        payout.with_user(self.reviewer).action_compute()
        self.assertTrue(payout.is_eligible)

    def test_exception_overrides_amount(self):
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        self.rating.rating = 'below'
        payout = self._payout()
        payout.write({'is_exception': True, 'exception_amount': 10000})
        with self.assertRaises(UserError):
            payout.with_user(self.reviewer).action_validate()
        payout.write({
            'exception_reason': 'Approved by leadership',
            'exception_approver_id': self.finance.id,
            'exception_attachment_ids': [(0, 0, {'name': 'approval.txt', 'raw': b'ok'})],
        })
        payout.with_user(self.reviewer).action_validate()
        self.assertEqual(payout.amount_final, 10000)

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def test_workflow_and_segregation(self):
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        payout = self._payout()
        with self.assertRaises(UserError):
            payout.with_user(self.finance).action_validate()
        payout.with_user(self.reviewer).action_validate()
        with self.assertRaises(UserError):
            payout.with_user(self.reviewer).action_approve()
        payout.with_user(self.finance).action_approve()
        self.assertEqual(payout.state, 'approved')
        self.assertEqual(payout.payout_date, date(2026, 4, 1))

    def test_one_payout_per_year(self):
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        self._payout()
        with self.assertRaises(ValidationError):
            self._payout()

    def test_generate_wizard(self):
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        wizard = self.env['bxi.eb.generate.payout.wizard'].with_user(self.reviewer).create({
            'reference_date': date(2025, 12, 1)})
        self.assertEqual((wizard.fy_start, wizard.fy_end), (self.fy_start, self.fy_end))
        action = wizard.action_generate()
        payout = self.env['bxi.eb.payout'].search(action['domain'])
        self.assertEqual(payout.employee_id, self.employee)
        self.assertAlmostEqual(payout.amount_final, 57600)

    def test_employee_sees_only_own_payout(self):
        other = self.env['hr.employee'].create({'name': 'Aman'})
        self.env['bxi.eb.performance.rating'].create({
            'employee_id': other.id, 'fy_start': self.fy_start, 'rating': 'meets'})
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite', employee=other)
        self._payout()
        self._payout(employee=other)
        visible = self.env['bxi.eb.payout'].with_user(self.employee_user).search([])
        self.assertEqual(visible.employee_id, self.employee)
