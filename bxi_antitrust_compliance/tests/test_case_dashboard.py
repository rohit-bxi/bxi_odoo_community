from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import ComplianceCommon


@tagged('post_install', '-at_install')
class TestCaseDashboard(ComplianceCommon):

    def _case(self):
        return self.env['antitrust.case'].with_user(self.cpo).create({
            'employee_ids': [(6, 0, self.employee.ids)],
            'summary': 'Price discussion at a trade association',
        })

    def test_case_lifecycle(self):
        case = self._case()
        self.assertTrue(case.name.startswith('CMP-CASE/'))
        with self.assertRaises(UserError):
            case.action_close()
        case.outcome = 'training_required'
        case.action_close()
        self.assertEqual(case.state, 'closed')
        self.assertEqual(case.closed_date, self.today)
        case.action_reopen()
        self.assertEqual(case.state, 'open')

    def test_cases_are_cpo_only(self):
        case = self._case()
        with self.assertRaises(AccessError):
            self.env['antitrust.case'].with_user(self.employee.user_id).search([('id', '=', case.id)])
        with self.assertRaises(AccessError):
            self.env['antitrust.case'].with_user(self.manager.user_id).create({
                'employee_ids': [(6, 0, self.employee.ids)], 'summary': 'x'})

    def test_employee_case_count(self):
        self._case()
        employee = self.employee.with_user(self.cpo)
        self.assertEqual(employee.compliance_case_count, 1)
        action = employee.action_view_compliance_cases()
        self.assertEqual(action['res_model'], 'antitrust.case')

    def test_dashboard(self):
        query = self.env['antitrust.query'].with_user(self.employee.user_id).create(
            {'subject': 'Doubt', 'situation': '<p>?</p>'})
        query.action_submit()
        interaction = self._interaction(interaction_type='joint_bid')
        interaction.action_submit()
        self._case()
        dashboard = self.env['antitrust.dashboard'].with_user(self.cpo).create({})
        self.assertGreaterEqual(dashboard.open_queries, 1)
        self.assertGreaterEqual(dashboard.interactions_to_review, 1)
        self.assertGreaterEqual(dashboard.open_cases, 1)
        for method in ('action_open_overdue', 'action_open_queries', 'action_open_incidents',
                       'action_open_interactions', 'action_open_unconfirmed', 'action_open_rfps',
                       'action_open_declarations', 'action_open_cases'):
            action = getattr(dashboard, method)()
            self.assertEqual(action['type'], 'ir.actions.act_window')
            self.env[action['res_model']].with_user(self.cpo).search(action['domain'])  # CPO can open every list

    def test_dashboard_is_cpo_only(self):
        with self.assertRaises(AccessError):
            self.env['antitrust.dashboard'].with_user(self.employee.user_id).create({})

    def test_settings(self):
        settings = self.env['res.config.settings'].create({
            'antitrust_contact_email': 'legal@example.com', 'bid_cpo_signoff': True,
        })
        settings.execute()
        self.assertEqual(self.env['antitrust.mixin']._contact_email(), 'legal@example.com')
        self.assertTrue(self.env.company.bid_cpo_signoff)
