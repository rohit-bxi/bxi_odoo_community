from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import ComplianceCommon


@tagged('post_install', '-at_install')
class TestQueryIncident(ComplianceCommon):

    # ── Legal queries ────────────────────────────────────────────────────
    def _query(self, **vals):
        values = {'subject': 'Trade association pricing survey', 'situation': '<p>Is it allowed?</p>'}
        values.update(vals)
        return self.env['antitrust.query'].with_user(self.employee.user_id).create(values)

    def test_query_defaults(self):
        query = self._query()
        self.assertTrue(query.name.startswith('CMP-Q/'))
        self.assertEqual(query.employee_id, self.employee)
        self.assertEqual(query.state, 'draft')

    def test_query_goes_to_contact_email_and_cpo(self):
        query = self._query(urgency='urgent')
        query.action_submit()
        self.assertEqual(query.state, 'submitted')
        self.assertTrue(self._cpo_activities(query))
        self.assertEqual(self._cpo_activities(query).date_deadline, self.today)
        messages = self._contact_messages(query)
        self.assertTrue(messages)
        self.assertEqual(self.env['antitrust.mixin']._contact_partner().email, 'compliance.test@example.com')
        self.assertIn('URGENT', messages[0].subject)

    def test_default_contact_email(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_antitrust_compliance.contact_email', False)
        self.assertEqual(self.env['antitrust.mixin']._contact_email(), 'internalIT@bxitech.com')

    def test_answer_and_close(self):
        query = self._query()
        query.action_submit()
        with self.assertRaises(UserError):
            query.action_close()  # the employee waits for the answer
        with self.assertRaises(UserError):
            query.with_user(self.cpo).action_answer()  # no answer written
        query.with_user(self.cpo).answer = '<p>Do not attend that part.</p>'
        query.with_user(self.cpo).action_answer()
        self.assertEqual(query.state, 'answered')
        self.assertEqual(query.answered_by_id, self.cpo)
        self.assertFalse(self._cpo_activities(query))
        self.assertTrue(query.sudo().message_ids.filtered(
            lambda m: self.employee.work_contact_id in m.partner_ids and 'answered' in m.body))
        query.action_close()
        self.assertEqual(query.state, 'closed')

    def test_employee_cannot_answer_or_edit_after_submit(self):
        query = self._query()
        with self.assertRaises(AccessError):
            query.write({'answer': '<p>self answer</p>'})
        query.action_submit()
        with self.assertRaises(UserError):
            query.write({'subject': 'Changed'})
        with self.assertRaises(UserError):
            query.action_answer()

    def test_query_is_confidential(self):
        query = self._query()
        Query = self.env['antitrust.query']
        self.assertFalse(Query.with_user(self.colleague.user_id).search([('id', '=', query.id)]))
        self.assertFalse(Query.with_user(self.manager.user_id).search([('id', '=', query.id)]),
                         "Not even the manager sees it")
        self.assertTrue(Query.with_user(self.cpo).search([('id', '=', query.id)]))

    # ── Incidents ────────────────────────────────────────────────────────
    def _incident(self, **vals):
        values = {
            'meeting_title': 'Industry round table',
            'meeting_type': 'industry_event',
            'other_parties': 'Competitor A, Competitor B',
            'description': '<p>Pricing for next year was discussed.</p>',
            'reservation_stated': 'yes',
            'discussion_stopped': 'no',
            'left_meeting': 'yes',
            'departure_recorded': 'yes',
            'departure_record_note': 'Noted in the minutes',
            'topic_ids': [(6, 0, self.env.ref('bxi_antitrust_compliance.topic_discussion_1').ids)],
        }
        values.update(vals)
        return self.env['antitrust.incident'].with_user(self.employee.user_id).create(values)

    def test_report_incident(self):
        incident = self._incident()
        incident.action_report()
        self.assertEqual(incident.state, 'reported')
        activities = self._cpo_activities(incident)
        self.assertTrue(activities)
        self.assertEqual(activities.date_deadline, self.today, "Legal is consulted immediately")
        self.assertTrue(self._contact_messages(incident))

    def test_incident_questions_required(self):
        incident = self._incident(reservation_stated=False)
        with self.assertRaises(UserError):
            incident.action_report()

    def test_explanation_when_staying(self):
        incident = self._incident(discussion_stopped='no', left_meeting='no', departure_recorded=False)
        with self.assertRaises(UserError):
            incident.action_report()
        incident.explanation = 'I was the presenter and informed Legal the same day.'
        incident.action_report()
        self.assertEqual(incident.state, 'reported')

    def test_departure_record_required_when_leaving(self):
        incident = self._incident(departure_recorded=False)
        with self.assertRaises(UserError):
            incident.action_report()

    def test_incident_review_and_case(self):
        incident = self._incident()
        incident.action_report()
        with self.assertRaises(UserError):
            incident.action_close()  # employee
        incident.with_user(self.cpo).action_start_review()
        self.assertEqual(incident.state, 'under_review')
        with self.assertRaises(UserError):
            incident.with_user(self.cpo).action_close()  # outcome missing
        incident.with_user(self.cpo).outcome = 'escalated_to_case'
        incident.with_user(self.cpo).action_close()
        self.assertEqual(incident.state, 'closed')
        self.assertEqual(incident.case_id.employee_ids, self.employee)
        self.assertEqual(incident.case_id.source, 'incident')

    def test_incident_locked_after_report(self):
        incident = self._incident()
        incident.action_report()
        with self.assertRaises(UserError):
            incident.write({'description': '<p>changed</p>'})
        with self.assertRaises(AccessError):
            incident.write({'outcome': 'no_action'})

    def test_incident_is_confidential(self):
        incident = self._incident()
        Incident = self.env['antitrust.incident']
        self.assertFalse(Incident.with_user(self.manager.user_id).search([('id', '=', incident.id)]))
        self.assertTrue(Incident.with_user(self.cpo).search([('id', '=', incident.id)]))
