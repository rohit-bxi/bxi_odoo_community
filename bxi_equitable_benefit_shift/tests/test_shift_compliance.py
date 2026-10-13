from datetime import date

from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestShiftCompliance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        set_param = cls.env['ir.config_parameter'].sudo().set_param
        set_param('bxi_equitable_benefit.fy_start_month', 4)
        set_param('bxi_equitable_benefit.proration_basis', 'months')
        set_param('bxi_equitable_benefit.allow_missing_rating', True)
        set_param('bxi_equitable_benefit.absence_source', 'leave')
        set_param('bxi_equitable_benefit.min_pattern_compliance', 80)
        cls.reviewer = new_test_user(
            cls.env, login='eb_shift_reviewer',
            groups='base.group_user,bxi_equitable_benefit.group_eb_revenue_assurance')
        Calendar = cls.env['resource.calendar']
        cls.day = Calendar.create({'name': 'EB Day Shift'})
        cls.night = Calendar.create({'name': 'EB Night Shift', 'eb_is_odd_shift': True})
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Neha', 'date_version': date(2020, 1, 1), 'resource_calendar_id': cls.day.id,
        })
        cls.employee.eb_annual_component_a = 480000
        cls.fy_start, cls.fy_end = date(2025, 4, 1), date(2026, 3, 31)
        assignment = cls.env['bxi.eb.assignment'].create({
            'employee_id': cls.employee.id, 'date_from': cls.fy_start,
            'work_pattern_id': cls.env.ref('bxi_equitable_benefit.work_pattern_odd_shift').id,
            'work_category': 'client', 'deployment': 'offshore', 'justification': 'Client night support',
        })
        assignment.action_submit()
        assignment.with_user(cls.reviewer).action_approve()

    def _shift(self, schedule, date_from, date_to, state='approved'):
        shift = self.env['bxi.shift.request'].sudo().create({
            'employee_id': self.employee.id,
            'date_from': date_from,
            'date_to': date_to,
            'requested_shift_id': schedule.id,
            'reason': 'Client night support',
        })
        shift.state = state
        return shift

    def _payout(self):
        payout = self.env['bxi.eb.payout'].create({
            'employee_id': self.employee.id, 'fy_start': self.fy_start, 'fy_end': self.fy_end,
            'period_end': self.fy_end,
        })
        payout.with_user(self.reviewer).action_compute()
        return payout

    def test_half_year_on_night_shift_request(self):
        self._shift(self.night, self.fy_start, date(2025, 9, 30))
        payout = self._payout()
        self.assertEqual(payout.line_ids.odd_shift_days, 183)
        self.assertIn('odd shift working schedule', payout.warning_note)
        # Flagged for review only.
        self.assertAlmostEqual(payout.amount_final, 52800)

    def test_full_year_on_night_shift_request(self):
        self._shift(self.night, self.fy_start, self.fy_end)
        payout = self._payout()
        self.assertEqual(payout.line_ids.odd_shift_percent, 100)
        self.assertNotIn('odd shift working schedule', payout.warning_note or '')

    def test_applied_shift_does_not_rewrite_the_past(self):
        shift = self._shift(self.night, date(2025, 10, 1), date(2026, 9, 30))
        # Applying the request overwrites the schedule of the contract.
        shift.write({'original_shift_id': self.day.id, 'schedule_applied': True})
        self.employee.resource_calendar_id = self.night
        self.assertEqual(self._payout().line_ids.odd_shift_days, 182)

    def test_refused_shift_ignored(self):
        self._shift(self.night, self.fy_start, self.fy_end, state='refused')
        self.assertEqual(self._payout().line_ids.odd_shift_percent, 0)
