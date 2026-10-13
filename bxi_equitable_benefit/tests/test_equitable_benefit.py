from datetime import date, datetime, time, timedelta

from freezegun import freeze_time

from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, TransactionCase, new_test_user, tagged


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
        set_param('bxi_equitable_benefit.absence_source', 'attendance')
        set_param('bxi_equitable_benefit.fnf_rating', 'latest')
        set_param('bxi_equitable_benefit.min_pattern_compliance', 80)
        set_param('bxi_equitable_benefit.payout_tds', 'incremental')
        set_param('bxi_equitable_benefit.auto_generate_days', 0)

        cls.reviewer = new_test_user(
            cls.env, login='eb_reviewer', groups='base.group_user,bxi_equitable_benefit.group_eb_revenue_assurance')
        cls.finance = new_test_user(
            cls.env, login='eb_finance', groups='base.group_user,bxi_equitable_benefit.group_eb_finance')
        cls.leader = new_test_user(
            cls.env, login='eb_leader', groups='base.group_user,bxi_equitable_benefit.group_eb_leadership')
        cls.employee_user = new_test_user(cls.env, login='eb_employee', groups='base.group_user')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Riya',
            'user_id': cls.employee_user.id,
            'date_version': date(2020, 1, 1),
            'tz': 'Asia/Kolkata',
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
        # Combinations the matrix leaves out are Not Applicable: a 0% row, so the pattern can still be recorded.
        self.assertEqual(Rate._find_rate(self.pattern_5, 'client', 'onsite', day, company).rate_percent, 0)
        self.assertEqual(Rate._find_rate(self.pattern_6, 'non_client', 'onsite', day, company).rate_percent, 9.6)
        self.assertEqual(Rate._find_rate(self.pattern_odd, 'client', 'onsite', day, company).rate_percent, 11)
        self.assertEqual(Rate._find_rate(self.pattern_odd, 'non_client', 'onsite', day, company).rate_percent, 0)

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
        pattern = self.env['bxi.eb.work.pattern'].create({'name': '4 Days Work from Office', 'code': 'WFO4'})
        assignment = self.env['bxi.eb.assignment'].create({
            'employee_id': self.employee.id, 'date_from': self.fy_start, 'work_pattern_id': pattern.id,
            'work_category': 'client', 'deployment': 'onsite', 'justification': 'Client SOW'})
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
            'work_category': 'non_client', 'deployment': 'onsite', 'justification': 'Release support weekends'})
        assignment.action_submit()
        with self.assertRaises(UserError):
            assignment.action_approve()
        with self.assertRaises(UserError):
            assignment.write({'justification': 'Other'})

    def test_employee_cannot_self_approve(self):
        Assignment = self.env['bxi.eb.assignment'].with_user(self.employee_user)
        vals = {
            'employee_id': self.employee.id, 'date_from': self.fy_start, 'work_pattern_id': self.pattern_6.id,
            'work_category': 'non_client', 'deployment': 'onsite', 'justification': 'Release support weekends'}
        with self.assertRaises(UserError):
            Assignment.create(dict(vals, state='approved'))
        with self.assertRaises(UserError):
            Assignment.create(dict(vals, approved_by_id=self.reviewer.id))
        assignment = Assignment.create(vals)
        with self.assertRaises(UserError):
            assignment.write({'state': 'approved'})
        with self.assertRaises(UserError):
            assignment.write({'approved_date': self.fy_start})
        assignment.action_submit()
        assignment.action_reset_draft()
        self.assertEqual(assignment.state, 'draft')

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

    def test_payout_statement_report_renders(self):
        self._assignment(self.pattern_5, self.fy_start)
        payout = self._payout()
        html, _ = self.env['ir.actions.report']._render_qweb_html(
            'bxi_equitable_benefit.report_payout_statement', payout.ids)
        self.assertIn(b'Equitable Benefit Statement', html)
        self.assertIn(self.employee.name.encode(), html)
        self.assertIn(payout.name.encode(), html)

    def test_hybrid_client_aligned_not_applicable(self):
        Rate = self.env['bxi.eb.rate']
        day = date(2025, 6, 1)
        for deployment in ('onsite', 'offshore'):
            rate = Rate._find_rate(self.pattern_hybrid, 'client', deployment, day, self.env.company)
            self.assertTrue(rate)
            self.assertEqual(rate.rate_percent, 0)

        self._assignment(self.pattern_hybrid, self.fy_start, category='client', deployment='offshore')
        payout = self._payout()
        self.assertTrue(payout.is_eligible)
        self.assertEqual(payout.amount_final, 0)

    def test_ensure_hybrid_client_rate_keeps_admin_rows(self):
        Rate = self.env['bxi.eb.rate'].with_context(active_test=False)
        domain = [('work_pattern_id', '=', self.pattern_hybrid.id), ('work_category', '=', 'client')]
        Rate._ensure_hybrid_client_rate()
        self.assertEqual(Rate.search_count(domain), 1)

        Rate.search(domain).write({'rate_percent': 2.5, 'deployment': 'offshore'})
        Rate._ensure_hybrid_client_rate()
        rows = Rate.search(domain)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.rate_percent, 2.5)

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
        # Finance is not the designated leadership authority
        with self.assertRaises(UserError):
            payout.with_user(self.reviewer).action_validate()
        payout.exception_approver_id = self.leader
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

    def test_payout_locked_after_draft(self):
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        payout = self._payout()
        payout.with_user(self.reviewer).action_validate()
        for user in (self.finance, self.reviewer):
            with self.assertRaises(UserError):
                payout.with_user(user).write({'is_exception': True, 'exception_amount': 1})
        with self.assertRaises(UserError):
            payout.with_user(self.finance).write({'state': 'approved'})
        # Finance picks the payroll month while approving
        payout.with_user(self.finance).payout_date = date(2026, 5, 15)
        payout.with_user(self.finance).action_approve()
        self.assertEqual(payout.payout_date, date(2026, 5, 15))
        with self.assertRaises(UserError):
            payout.with_user(self.finance).payout_date = date(2026, 6, 15)
        with self.assertRaises(UserError):
            payout.with_user(self.finance).action_reset_draft()
        with self.assertRaises(UserError):
            payout.with_user(self.employee_user).action_cancel()
        payout.with_user(self.reviewer).action_reset_draft()
        payout.with_user(self.reviewer).write({'is_exception': True, 'exception_amount': 1})
        self.assertEqual(payout.amount_final, 1)

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

    # ------------------------------------------------------------------
    # Separation (Full & Final Settlement)
    # ------------------------------------------------------------------
    def test_fnf_uses_latest_rating(self):
        """Nobody has a rating for the year they leave in: the latest one applies."""
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        payout = self.env['bxi.eb.payout']._create_fnf_payout(self.employee, date(2026, 6, 30))
        self.assertTrue(payout.is_eligible)
        self.assertIn('FY 2025-26', payout.rating)
        self.assertIn('latest available rating', payout.warning_note)
        self.assertAlmostEqual(payout.amount_final, 600000 * 0.096 * 3 / 12)

        self.env['ir.config_parameter'].sudo().set_param('bxi_equitable_benefit.fnf_rating', 'required')
        payout.with_user(self.reviewer).action_compute()
        self.assertFalse(payout.is_eligible)

    def test_fnf_settles_unpaid_previous_year(self):
        """Leaving before the annual payout cycle: the closed year is paid in the FNF too."""
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        last_day = date(2026, 5, 31)
        current = self.env['bxi.eb.payout']._create_fnf_payout(self.employee, last_day)
        previous = self.env['bxi.eb.payout'].search([
            ('employee_id', '=', self.employee.id), ('fy_start', '=', self.fy_start)])
        self.assertEqual(previous.payout_type, 'annual')
        self.assertEqual(previous.separation_date, last_day)
        self.assertAlmostEqual(previous.amount_final, 57600)
        self.assertEqual(current.payout_type, 'fnf')
        self.assertAlmostEqual(current.amount_final, 600000 * 0.096 * 2 / 12)
        for payout in previous | current:
            payout.with_user(self.reviewer).action_validate()
            payout.with_user(self.finance).action_approve()
            self.assertEqual(payout.payout_date, last_day)

    def test_fnf_brings_forward_approved_payout(self):
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        previous = self._payout()
        previous.with_user(self.reviewer).action_validate()
        previous.with_user(self.finance).action_approve()
        previous.payout_date = date(2026, 6, 30)
        self.env['bxi.eb.payout']._create_fnf_payout(self.employee, date(2026, 5, 31))
        self.assertEqual(previous.state, 'approved')
        self.assertEqual(previous.payout_date, date(2026, 5, 31))
        self.assertEqual(previous.separation_date, date(2026, 5, 31))

    def test_resignation_and_change_of_last_day(self):
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        resignation = self.env['employee.resignation'].create({
            'employee_id': self.employee.id,
            'resignation_date': date(2025, 10, 1),
            'last_working_day': date(2025, 11, 30),
            'reason': 'personal',
            'resignation_body': '<p>Resigning</p>',
        })
        resignation.action_submit()
        resignation.action_approve()
        payout = self.env['bxi.eb.payout'].search([('resignation_id', '=', resignation.id)])
        self.assertEqual(payout.payout_type, 'fnf')
        self.assertAlmostEqual(payout.amount_final, 600000 * 0.096 * 8 / 12)
        self.assertIn(self.reviewer, payout.activity_ids.user_id)

        resignation.approved_last_working_day = date(2025, 12, 31)
        self.assertEqual(payout.period_end, date(2025, 12, 31))
        self.assertAlmostEqual(payout.amount_final, 600000 * 0.096 * 9 / 12)
        self.assertEqual(len(payout.activity_ids.filtered(lambda a: a.user_id == self.reviewer)), 1)

    def test_departure_without_resignation(self):
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        self.employee.departure_date = date(2025, 9, 30)
        payout = self.env['bxi.eb.payout'].search([('employee_id', '=', self.employee.id)])
        self.assertEqual(payout.payout_type, 'fnf')
        self.assertEqual(payout.period_end, date(2025, 9, 30))
        self.assertAlmostEqual(payout.amount_final, 28800)

    # ------------------------------------------------------------------
    # Leave and attendance
    # ------------------------------------------------------------------
    def _leave(self, leave_type, date_from, date_to):
        leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'holiday_status_id': leave_type.id,
            'request_date_from': date_from,
            'request_date_to': date_to,
        })
        if leave.state != 'validate':
            leave.action_approve()
        if leave.state != 'validate':
            leave.action_validate()
        return leave

    def _leave_type(self, name, **vals):
        return self.env['hr.leave.type'].create(dict({
            'name': name, 'requires_allocation': False, 'leave_validation_type': 'no_validation'}, **vals))

    def test_unpaid_leave_counts_working_days(self):
        """A Friday to Monday unpaid leave is 2 days, not 4 calendar days."""
        self.env['ir.config_parameter'].sudo().set_param('bxi_equitable_benefit.unpaid_leave_threshold_days', 1)
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        self._leave(self._leave_type('EB Unpaid', eb_is_unpaid=True), date(2025, 5, 2), date(2025, 5, 5))
        payout = self._payout()
        self.assertEqual(payout.unpaid_leave_days, 2)
        self.assertTrue(payout.unpaid_leave_prorated)
        self.assertAlmostEqual(payout.amount_final, round(57600 * 363 / 365, 2))

    def test_flag_default_unpaid_leave_types(self):
        LeaveType = self.env['hr.leave.type'].with_context(active_test=False)
        LeaveType.search([]).write({'eb_is_unpaid': False})
        lwp = self._leave_type('Leave Without Pay')
        paid = self._leave_type('Privilege Leave')
        LeaveType._eb_flag_default_unpaid_types()
        self.assertTrue(lwp.eb_is_unpaid)
        self.assertFalse(paid.eb_is_unpaid)
        # An administrator's choice is kept
        lwp.eb_is_unpaid = False
        paid.eb_is_unpaid = True
        LeaveType._eb_flag_default_unpaid_types()
        self.assertFalse(lwp.eb_is_unpaid)

    def _attend(self, days):
        # 09:30 to 17:30 India time
        Attendance = self.env['hr.attendance']
        # bxi_attendance (when installed) enforces GPS/work-location checks on
        # check-in/out. Those are UI guards, irrelevant to the attendance data
        # this helper seeds, so skip them via the auto-checkout bypass when the
        # field is available (EB counts attendance by employee/date regardless).
        extra = {'is_auto_checkout': True} if 'is_auto_checkout' in Attendance._fields else {}
        Attendance.create([{
            'employee_id': self.employee.id,
            'check_in': datetime.combine(day, time(4, 0)),
            'check_out': datetime.combine(day, time(12, 0)),
            **extra,
        } for day in days])

    @staticmethod
    def _weekdays(date_from, date_to, weekdays=(0, 1, 2, 3, 4)):
        days = [date_from + timedelta(days=offset) for offset in range((date_to - date_from).days + 1)]
        return [day for day in days if day.weekday() in weekdays]

    def test_unauthorized_absence_from_attendance(self):
        if 'hr.attendance' not in self.env:
            self.skipTest("hr_attendance is not installed")
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        absent = {date(2025, 4, 14), date(2025, 4, 15), date(2025, 4, 16), date(2025, 4, 17)}
        self._attend([day for day in self._weekdays(date(2025, 4, 1), date(2025, 4, 30)) if day not in absent])
        payout = self._payout(period_end=date(2025, 4, 30))
        self.assertEqual(payout.unauthorized_absence_days, 4)
        self.assertFalse(payout.is_eligible)

        # Approved leave is not an unauthorized absence
        self._leave(self._leave_type('EB Casual'), date(2025, 4, 14), date(2025, 4, 15))
        payout.with_user(self.reviewer).action_compute()
        self.assertEqual(payout.unauthorized_absence_days, 2)
        self.assertTrue(payout.is_eligible)

        self.env['ir.config_parameter'].sudo().set_param('bxi_equitable_benefit.absence_source', 'leave')
        payout.with_user(self.reviewer).action_compute()
        self.assertEqual(payout.unauthorized_absence_days, 0)

    def test_pattern_compliance(self):
        if 'hr.attendance' not in self.env:
            self.skipTest("hr_attendance is not installed")
        set_param = self.env['ir.config_parameter'].sudo().set_param
        set_param('bxi_equitable_benefit.absence_source', 'leave')
        set_param('bxi_equitable_benefit.min_pattern_compliance', 90)
        self._assignment(self.pattern_6, self.fy_start, date(2025, 4, 30), deployment='onsite')
        self._attend(self._weekdays(date(2025, 4, 1), date(2025, 4, 30), weekdays=(0, 1, 2, 3, 4, 5)))
        payout = self._payout()
        line = payout.line_ids
        self.assertTrue(line.compliance_checked)
        self.assertEqual(line.attended_days, 26)
        self.assertEqual(line.compliance_percent, 100)
        self.assertFalse(payout.warning_note)

        # Mondays are work from home: they are not office days
        home = self.env['hr.work.location'].create({
            'name': 'Home', 'location_type': 'home', 'address_id': self.env.company.partner_id.id})
        self.employee.monday_location_id = home
        payout.with_user(self.reviewer).action_compute()
        self.assertEqual(payout.line_ids.attended_days, 22)
        self.assertIn('office days attended', payout.warning_note)
        self.assertTrue(payout.is_eligible, "The compliance check never blocks the payout")

    # ------------------------------------------------------------------
    # Other policy points
    # ------------------------------------------------------------------
    def test_compliance_case_disciplinary_outcome(self):
        if 'antitrust.case' not in self.env:
            self.skipTest("bxi_antitrust_compliance is not installed")
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        case = self.env['antitrust.case'].create({
            'employee_ids': [(6, 0, self.employee.ids)],
            'summary': 'Shared pricing with a competitor',
            'outcome': 'disciplinary',
        })
        self.env.cr.execute("UPDATE antitrust_case SET create_date = %s WHERE id = %s",
                            (datetime(2025, 6, 1), case.id))
        case.invalidate_recordset(['create_date'])
        payout = self._payout()
        self.assertFalse(payout.is_eligible)
        self.assertEqual(payout.disciplinary_count, 1)

    def test_missing_component_a_blocks_validation(self):
        other = self.env['hr.employee'].create({'name': 'Aman', 'date_version': date(2020, 1, 1)})
        self.env['bxi.eb.performance.rating'].create({
            'employee_id': other.id, 'fy_start': self.fy_start, 'rating': 'meets'})
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite', employee=other)
        payout = self._payout(employee=other)
        self.assertTrue(payout.missing_component_a)
        self.assertIn('Component A', payout.warning_note)
        with self.assertRaises(UserError):
            payout.with_user(self.reviewer).action_validate()

    def test_new_pattern_closes_ongoing_one(self):
        six_day = self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        five_day = self.env['bxi.eb.assignment'].create({
            'employee_id': self.employee.id, 'date_from': date(2025, 10, 1), 'work_pattern_id': self.pattern_5.id,
            'work_category': 'client', 'deployment': 'offshore', 'justification': 'New SOW'})
        five_day.action_submit()
        self.assertIn(self.reviewer, five_day.activity_ids.user_id)
        five_day.with_user(self.reviewer).action_approve()
        self.assertEqual(six_day.date_to, date(2025, 9, 30))
        self.assertFalse(five_day.activity_ids)
        self.assertAlmostEqual(self._payout().amount_final, 28800 + 15000)

    def test_policy_suspension(self):
        self.employee.company_id.eb_suspended_from = date(2025, 10, 1)
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        self.assertAlmostEqual(self._payout().amount_final, 28800)
        late = self.env['bxi.eb.assignment'].create({
            'employee_id': self.employee.id, 'date_from': date(2025, 11, 1), 'work_pattern_id': self.pattern_5.id,
            'work_category': 'client', 'deployment': 'offshore', 'justification': 'SOW'})
        with self.assertRaises(UserError):
            late.action_submit()

    def test_tds_on_payout(self):
        """2,00,000 of annual income taxed at 20% then 25%, plus 4% cess."""
        self.employee.employee_ctc = 2000000
        self.assertAlmostEqual(self.employee.get_equitable_benefit_tds(100000), 22100)
        self.env['ir.config_parameter'].sudo().set_param('bxi_equitable_benefit.payout_tds', 'none')
        self.assertEqual(self.employee.get_equitable_benefit_tds(100000), 0)

        eqb = self.env.ref('bxi_equitable_benefit.hr_rule_equitable_benefit')
        tds = self.env.ref('bxi_equitable_benefit.hr_rule_equitable_benefit_tds')
        for structure in self.env['hr.payroll.structure'].search([('rule_ids', 'in', eqb.id)]):
            self.assertIn(tds, structure.rule_ids)

    def test_tds_marginal_relief(self):
        """Crossing the ₹12,00,000 rebate limit: the tax is capped at the income above it (plus cess),
        never more than the benefit itself."""
        self.employee.employee_ctc = 1250000
        self.assertAlmostEqual(self.employee.get_equitable_benefit_tds(60000), 36400)

    def test_approval_after_payroll_closed(self):
        """Approving after the April payroll is done moves the payout to the next payroll."""
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        april = self.env['hr.payslip'].create({
            'employee_id': self.employee.id, 'date_from': date(2026, 4, 1), 'date_to': date(2026, 4, 30)})
        april.state = 'done'
        payout = self._payout()
        payout.with_user(self.reviewer).action_validate()
        payout.with_user(self.finance).payout_date = date(2026, 4, 15)
        with self.assertRaises(UserError):
            payout.with_user(self.finance).action_approve()
        payout.with_user(self.finance).payout_date = False
        payout.with_user(self.finance).action_approve()
        self.assertEqual(payout.payout_date, date(2026, 5, 1))

    def test_component_a_missing_flagged_on_assignment(self):
        other = self.env['hr.employee'].create({'name': 'Aman', 'date_version': date(2020, 1, 1)})
        assignment = self._assignment(self.pattern_6, self.fy_start, deployment='onsite', employee=other)
        hybrid = self._assignment(self.pattern_hybrid, self.fy_start, category='non_client')
        self.assertTrue(assignment.component_a_missing)
        self.assertFalse(hybrid.component_a_missing)
        Assignment = self.env['bxi.eb.assignment'].with_user(self.reviewer)
        missing = Assignment.search([('component_a_missing', '=', True)])
        self.assertIn(assignment, missing)
        self.assertNotIn(hybrid, missing)
        other.eb_annual_component_a = 500000
        assignment.invalidate_recordset(['component_a_missing'])
        self.assertFalse(assignment.component_a_missing)

    def test_deployment_change_prepares_successor(self):
        """Moving onsite (international deputation): a draft onsite successor is prepared for review."""
        current = self._assignment(self.pattern_6, self.fy_start)
        self.employee._eb_deployment_changed('onsite', date(2025, 9, 1), 'International deputation DEP/1')
        successor = self.env['bxi.eb.assignment'].search([
            ('employee_id', '=', self.employee.id), ('id', '!=', current.id)])
        self.assertEqual(successor.state, 'draft')
        self.assertEqual(successor.deployment, 'onsite')
        self.assertEqual(successor.date_from, date(2025, 9, 1))
        self.assertEqual(successor.work_pattern_id, self.pattern_6)
        self.assertIn(self.reviewer, successor.activity_ids.user_id)
        successor.action_submit()
        successor.with_user(self.reviewer).action_approve()
        self.assertEqual(current.date_to, date(2025, 8, 31))
        # Same deployment again: nothing to do.
        self.employee._eb_deployment_changed('onsite', date(2025, 10, 1), 'International deputation DEP/1')
        self.assertEqual(self.env['bxi.eb.assignment'].search_count([('employee_id', '=', self.employee.id)]), 2)

    def test_generate_skips_not_applicable(self):
        other = self.env['hr.employee'].create({'name': 'Neha'})
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        self._assignment(self.pattern_hybrid, self.fy_start, category='non_client', employee=other)
        payouts = self.env['bxi.eb.payout']._generate_annual_payouts(self.fy_start, self.fy_end)
        self.assertEqual(payouts.employee_id, self.employee)

    def test_cron_generates_once_after_year_close(self):
        set_param = self.env['ir.config_parameter'].sudo().set_param
        set_param('bxi_equitable_benefit.auto_generate_days', 15)
        set_param('bxi_equitable_benefit.last_auto_generated_fy', False)
        self._assignment(self.pattern_6, self.fy_start, deployment='onsite')
        Payout = self.env['bxi.eb.payout']
        domain = [('employee_id', '=', self.employee.id), ('fy_start', '=', self.fy_start)]
        with freeze_time('2026-04-10'):
            Payout._cron_generate_annual_payouts()
        self.assertFalse(Payout.search(domain))
        with freeze_time('2026-04-20'):
            Payout._cron_generate_annual_payouts()
            payout = Payout.search(domain)
            self.assertAlmostEqual(payout.amount_final, 57600)
            payout.unlink()
            Payout._cron_generate_annual_payouts()
        self.assertFalse(Payout.search(domain))

    def test_payout_form_fills_the_year(self):
        """Entering any date of the year is enough; changing the year moves the other dates with it."""
        with Form(self.env['bxi.eb.payout']) as form:
            form.employee_id = self.employee
            form.fy_start = date(2025, 7, 15)
            self.assertEqual(form.fy_start, self.fy_start)
            self.assertEqual(form.fy_end, self.fy_end)
            self.assertEqual(form.period_end, self.fy_end)
            form.fy_start = date(2024, 4, 1)
            self.assertEqual(form.fy_end, date(2025, 3, 31))
            self.assertEqual(form.period_end, date(2025, 3, 31))
        payout = form.record
        with self.assertRaises(ValidationError):
            payout.period_end = date(2025, 6, 30)

    # ------------------------------------------------------------------
    # Odd shift compliance
    # ------------------------------------------------------------------
    def _calendars(self):
        Calendar = self.env['resource.calendar']
        return Calendar.create({'name': 'EB Day Shift'}), Calendar.create({'name': 'EB Night Shift', 'eb_is_odd_shift': True})

    def test_odd_shift_not_checked_until_configured(self):
        self.env['resource.calendar'].search([]).eb_is_odd_shift = False
        self._assignment(self.pattern_odd, self.fy_start)
        payout = self._payout()
        self.assertFalse(payout.line_ids.shift_checked)
        self.assertAlmostEqual(payout.amount_final, 66000)

    def test_odd_shift_worked_on_odd_schedule(self):
        _day, night = self._calendars()
        self.employee.resource_calendar_id = night
        self._assignment(self.pattern_odd, self.fy_start)
        payout = self._payout()
        self.assertTrue(payout.line_ids.shift_checked)
        self.assertEqual(payout.line_ids.odd_shift_percent, 100)
        self.assertNotIn('odd shift working schedule', payout.warning_note or '')

    def test_odd_shift_worked_on_day_schedule_flagged(self):
        day, _night = self._calendars()
        self.employee.resource_calendar_id = day
        self._assignment(self.pattern_odd, self.fy_start)
        payout = self._payout()
        self.assertEqual(payout.line_ids.odd_shift_percent, 0)
        self.assertIn('odd shift working schedule', payout.warning_note)
        # A warning for review, never a block.
        self.assertTrue(payout.is_eligible)
        self.assertAlmostEqual(payout.amount_final, 66000)

