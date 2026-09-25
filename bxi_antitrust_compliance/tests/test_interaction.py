from datetime import timedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import ComplianceCommon


@tagged('post_install', '-at_install')
class TestInteraction(ComplianceCommon):

    def test_low_risk_is_cleared(self):
        interaction = self._interaction()
        self.assertEqual(interaction.risk_level, 'low')
        interaction.action_submit()
        self.assertEqual(interaction.state, 'cleared')
        self.assertFalse(self._cpo_activities(interaction))

    def test_commitments_required(self):
        interaction = self._interaction(commit_report=False)
        with self.assertRaises(UserError):
            interaction.action_submit()

    def test_prohibited_topics_listed(self):
        self.assertIn('Wage-fixing', self._interaction().topics_html)

    def test_high_risk_goes_to_cpo(self):
        for kind in ('competitor_meeting', 'joint_bid', 'benchmarking'):
            interaction = self._interaction(interaction_type=kind)
            self.assertEqual(interaction.risk_level, 'high')
            interaction.action_submit()
            self.assertEqual(interaction.state, 'cpo_review')
            self.assertTrue(self._cpo_activities(interaction))

    def test_cpo_clears_with_conditions(self):
        interaction = self._interaction(interaction_type='joint_bid')
        interaction.action_submit()
        with self.assertRaises(UserError):
            interaction.action_clear()
        interaction.with_user(self.cpo).write({'conditions': 'Legal reviews the teaming agreement',
                                               'cpo_attendance': True})
        interaction.with_user(self.cpo).action_clear()
        self.assertEqual(interaction.state, 'cleared')
        self.assertEqual(interaction.reviewed_by_id, self.cpo)
        self.assertTrue(interaction.sudo().message_ids.filtered(lambda m: 'Legal reviews' in m.body))

    def test_cpo_rejects_with_reason(self):
        interaction = self._interaction(interaction_type='benchmarking')
        interaction.action_submit()
        with self.assertRaises(UserError):
            interaction.with_user(self.cpo).action_reject()
        interaction.with_user(self.cpo).reject_reason = 'Salary benchmarking with competitors is not allowed'
        interaction.with_user(self.cpo).action_reject()
        self.assertEqual(interaction.state, 'rejected')

    def test_confirm_only_after_event(self):
        interaction = self._interaction()
        interaction.action_submit()
        with self.assertRaises(UserError):
            interaction.action_confirm_no_issue()
        interaction.sudo().event_date = self.today
        interaction.action_confirm_no_issue()
        self.assertEqual(interaction.state, 'done')
        self.assertEqual(interaction.post_declared_date, self.today)

    def test_report_incident_prefills(self):
        interaction = self._interaction(interaction_type='competitor_meeting')
        interaction.action_submit()
        interaction.with_user(self.cpo).action_clear()
        action = interaction.action_report_incident()
        incident = self.env['antitrust.incident'].browse(action['res_id'])
        self.assertEqual(interaction.state, 'incident')
        self.assertEqual(incident.interaction_id, interaction)
        self.assertEqual(incident.other_parties, 'Competitor Ltd')
        self.assertEqual(incident.meeting_type, 'competitor')
        self.assertEqual(incident.state, 'draft', "The employee completes and reports it")
        incident.with_user(self.employee.user_id).write({
            'reservation_stated': 'yes', 'discussion_stopped': 'yes', 'left_meeting': 'no',
        })
        incident.with_user(self.employee.user_id).action_report()
        self.assertEqual(incident.state, 'reported')

    def test_post_event_follow_up(self):
        interaction = self._interaction()
        interaction.action_submit()
        Interaction = self.env['antitrust.interaction']
        interaction.sudo().event_date = self.today - timedelta(days=2)
        Interaction._cron_post_event_follow_up()
        self.assertTrue(interaction.post_reminded)
        self.assertFalse(interaction.post_escalated)
        interaction.sudo().event_date = self.today - timedelta(days=7)
        Interaction._cron_post_event_follow_up()
        self.assertTrue(interaction.post_escalated)
        self.assertTrue(self._cpo_activities(interaction))

    def test_manager_reads_team_declarations(self):
        interaction = self._interaction()
        as_manager = self.env['antitrust.interaction'].with_user(self.manager.user_id)
        self.assertEqual(as_manager.search([('id', '=', interaction.id)]), interaction)
        with self.assertRaises(AccessError):
            interaction.with_user(self.manager.user_id).write({'purpose': 'changed'})
        self.assertFalse(self.env['antitrust.interaction'].with_user(self.colleague.user_id).search(
            [('id', '=', interaction.id)]))

    def test_locked_after_submit(self):
        interaction = self._interaction()
        interaction.action_submit()
        with self.assertRaises(UserError):
            interaction.write({'organisations': 'Someone else'})
