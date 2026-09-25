from odoo.http import Request
from odoo.tests import HttpCase, tagged

from .common import PolicyTestMixin


@tagged('post_install', '-at_install')
class TestPolicyPortal(PolicyTestMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_policy_data()

    def setUp(self):
        super().setUp()
        self.version = self._publish()
        self.ack = self._ack_of(self.version, self.employee)
        login = self.employee.user_id.login
        self.authenticate(login, login)

    def _post(self, url, data=None):
        response = self.url_open(url, data=dict(data or {}, csrf_token=Request.csrf_token(self)),
                                 allow_redirects=False)
        self.env.invalidate_all()
        return response

    def test_pages(self):
        self.assertIn('/my/policies', self.url_open('/my').text)
        page = self.url_open('/my/policies')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Test Antitrust Policy', page.text)
        self.assertEqual(self.url_open(f'/my/policies/{self.ack.id}').status_code, 200)

    def test_preview_marks_document_opened(self):
        response = self.url_open(f'/bxi_hr_policy/preview/version/{self.version.id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'application/pdf')
        self.env.invalidate_all()
        self.assertTrue(self.ack.document_opened)

    def test_acknowledge_on_portal(self):
        response = self._post(f'/my/policies/{self.ack.id}/acknowledge', {'agree': 'on'})
        self.assertIn('error=open', response.headers['Location'])
        self.url_open(f'/bxi_hr_policy/preview/version/{self.version.id}')
        response = self._post(f'/my/policies/{self.ack.id}/acknowledge')
        self.assertIn('error=agree', response.headers['Location'])
        response = self._post(f'/my/policies/{self.ack.id}/acknowledge', {'agree': 'on'})
        self.assertTrue(response.headers['Location'].endswith('/my/policies'))
        self.assertEqual(self.ack.state, 'acknowledged')
        self.assertEqual(self.ack.channel, 'portal')
        self.assertTrue(self.ack.ip_address)

    def test_other_employees_acknowledgement(self):
        other = self._ack_of(self.version, self.manager)
        self.assertEqual(self.url_open(f'/my/policies/{other.id}').status_code, 404)
        self.assertEqual(self._post(f'/my/policies/{other.id}/acknowledge', {'agree': 'on'}).status_code, 404)

    def test_draft_version_not_previewable(self):
        draft = self._version()
        self.assertEqual(self.url_open(f'/bxi_hr_policy/preview/version/{draft.id}').status_code, 404)

    def test_portal_lock(self):
        self.policy.block_portal_until_ack = True
        response = self.url_open('/my/employee-expenses', allow_redirects=False)
        self.assertNotIn('/my/policies', response.headers.get('Location', ''), "Only overdue locks the portal")
        self._shift_dates(self.ack, 8)
        self.env['hr.policy.acknowledgement']._cron_process_acknowledgements()
        response = self.url_open('/my/home', allow_redirects=False)
        self.assertIn('/my/policies', response.headers.get('Location', ''))
        self.assertEqual(self.url_open('/my/policies', allow_redirects=False).status_code, 200)

    def test_no_lock_when_disabled(self):
        self._shift_dates(self.ack, 8)
        self.env['hr.policy.acknowledgement']._cron_process_acknowledgements()
        response = self.url_open('/my/home', allow_redirects=False)
        self.assertNotIn('/my/policies', response.headers.get('Location', ''))
