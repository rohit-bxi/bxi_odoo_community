from urllib.parse import unquote

from odoo.http import Request
from odoo.tests import HttpCase, tagged

from .common import ComplianceTestMixin


@tagged('post_install', '-at_install')
class TestCompliancePortal(ComplianceTestMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_compliance_data()

    def setUp(self):
        super().setUp()
        login = self.employee.user_id.login
        self.authenticate(login, login)

    def _post(self, url, data):
        response = self.url_open(url, data=dict(data, csrf_token=Request.csrf_token(self)), allow_redirects=False)
        self.env.invalidate_all()
        return response

    def _mine(self, model):
        return self.env[model].search([('employee_id', '=', self.employee.id)])

    def test_pages(self):
        for url in ('/my/compliance', '/my/compliance/query', '/my/compliance/incident', '/my/compliance/interaction'):
            self.assertEqual(self.url_open(url).status_code, 200, url)
        self.assertIn('compliance.test@example.com', self.url_open('/my/compliance').text)
        self.assertIn('/my/compliance', self.url_open('/my').text)

    def test_query(self):
        response = self._post('/my/compliance/query', {'subject': 'Doubt', 'situation': 'Line 1\n<b>Line 2</b>',
                                                       'urgency': 'urgent'})
        self.assertEqual(response.status_code, 303)
        query = self._mine('antitrust.query')
        self.assertEqual(query.state, 'submitted')
        self.assertEqual(query.urgency, 'urgent')
        self.assertIn('&lt;b&gt;Line 2', query.situation, "Portal text is escaped")

    def test_query_missing_fields(self):
        response = self._post('/my/compliance/query', {'subject': 'Doubt'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('alert-danger', response.text)
        self.assertFalse(self._mine('antitrust.query'))

    def test_incident(self):
        topic = self.env.ref('bxi_antitrust_compliance.topic_discussion_7')
        response = self._post('/my/compliance/incident', {
            'meeting_title': 'HR forum', 'meeting_type': 'trade_association', 'incident_date': '2026-09-01',
            'other_parties': 'Competitor HR heads', 'description': 'Salary freeze was proposed',
            'topic_ids': [topic.id], 'reservation_stated': 'yes', 'discussion_stopped': 'no',
            'left_meeting': 'yes', 'departure_recorded': 'yes', 'departure_record_note': 'Minutes',
        })
        self.assertEqual(response.status_code, 303)
        incident = self._mine('antitrust.incident')
        self.assertEqual(incident.state, 'reported')
        self.assertEqual(incident.topic_ids, topic)

    def test_incident_validation_rolls_back(self):
        response = self._post('/my/compliance/incident', {
            'meeting_title': 'HR forum', 'incident_date': '2026-09-01', 'other_parties': 'X',
            'description': 'Y', 'reservation_stated': 'yes', 'discussion_stopped': 'no', 'left_meeting': 'no',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('explain', response.text)
        self.assertFalse(self._mine('antitrust.incident'))

    def test_interaction_and_confirmation(self):
        response = self._post('/my/compliance/interaction', {
            'interaction_type': 'industry_event', 'event_date': '2026-09-01', 'organisations': 'Competitor Ltd',
            'purpose': 'Panel', 'commit_no_topics': 'on', 'commit_report': 'on',
        })
        self.assertEqual(response.status_code, 303)
        interaction = self._mine('antitrust.interaction')
        self.assertEqual(interaction.state, 'cleared')
        response = self._post(f'/my/compliance/interaction/{interaction.id}/confirm', {})
        self.assertIn('Thank you', unquote(response.headers['Location']))
        self.assertEqual(interaction.state, 'done')

    def test_cannot_confirm_others_interaction(self):
        other = self._interaction(user=self.colleague.user_id, employee_id=self.colleague.id)
        other.action_submit()
        response = self._post(f'/my/compliance/interaction/{other.id}/confirm', {})
        self.assertEqual(response.status_code, 404)
