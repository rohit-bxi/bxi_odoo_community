from datetime import timedelta
from urllib.parse import unquote

from odoo.http import Request
from odoo.tests import HttpCase, tagged

from .common import SalaryAdvanceTestMixin, make_pdf


@tagged('post_install', '-at_install')
class TestSalaryAdvancePortal(SalaryAdvanceTestMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_salary_advance_data()

    def setUp(self):
        super().setUp()
        login = self.employee.user_id.login
        self.authenticate(login, login)

    def _post(self, url, data=None, files=None):
        data = dict(data or {}, csrf_token=Request.csrf_token(self))
        response = self.url_open(url, data=data, files=files, allow_redirects=False)
        self.env.invalidate_all()  # the request ran in the server; drop the stale cache
        return response

    def _form_file(self):
        return {'request_form': ('signed.pdf', make_pdf('Signed request form'), 'application/pdf')}

    def test_pages_render(self):
        advance = self._new_advance()
        for url in ('/my', '/my/salary-advances', '/my/salary-advances/new', f'/my/salary-advances/{advance.id}'):
            response = self.url_open(url)
            self.assertEqual(response.status_code, 200, url)
        self.assertIn('/my/salary-advances', self.url_open('/my').text)
        self.assertIn(advance.name, self.url_open('/my/salary-advances').text)
        self.assertIn('60,000', self.url_open('/my/salary-advances/new').text)

    def test_other_employees_advance_is_not_found(self):
        other = self._new_advance(employee=self.manager)
        self.assertEqual(self.url_open(f'/my/salary-advances/{other.id}').status_code, 404)
        self.assertEqual(self.url_open(f'/my/salary-advances/{other.id}/request-form').status_code, 404)
        self.assertEqual(self.url_open('/my/salary-advances/999999').status_code, 404)

    def test_submit_new_advance(self):
        response = self._post('/my/salary-advances/new', {
            'category': 'emergency', 'emergency_type': 'birth', 'amount_requested': '30000',
            'reason': 'Birth of our daughter', 'submit_now': '1',
        }, files=self._form_file())
        self.assertEqual(response.status_code, 303)
        advance = self.env['bxi.salary.advance'].search([('employee_id', '=', self.employee.id)])
        self.assertEqual(advance.state, 'submitted')
        self.assertEqual(advance.emergency_type, 'birth')
        self.assertEqual(advance.amount_requested, 30000)
        self.assertEqual(len(advance.request_form_ids), 1)
        self.assertTrue(response.headers['Location'].endswith(f'/my/salary-advances/{advance.id}'))

    def test_error_keeps_nothing(self):
        response = self._post('/my/salary-advances/new', {
            'category': 'emergency', 'emergency_type': 'birth', 'amount_requested': '70000', 'submit_now': '1',
        }, files=self._form_file())
        self.assertEqual(response.status_code, 200)
        self.assertIn('75%', response.text)
        self.assertFalse(self.env['bxi.salary.advance'].search([('employee_id', '=', self.employee.id)]))

    def test_draft_upload_and_submit(self):
        response = self._post('/my/salary-advances/new', {
            'category': 'housing', 'tenancy_months': '12', 'amount_requested': '90000',
        })
        advance = self.env['bxi.salary.advance'].search([('employee_id', '=', self.employee.id)])
        self.assertEqual(advance.state, 'draft')
        page = self.url_open(f'/my/salary-advances/{advance.id}').text
        self.assertIn('Upload the rental agreement', page)

        response = self._post(f'/my/salary-advances/{advance.id}/submit')
        self.assertIn('rental agreement', unquote(response.headers['Location']))
        self.assertEqual(advance.state, 'draft')

        self._post(f'/my/salary-advances/{advance.id}/documents', files={
            'request_form': ('signed.pdf', make_pdf('Signed'), 'application/pdf'),
            'rental_agreement': ('rent.pdf', make_pdf('Rent'), 'application/pdf'),
        })
        self._post(f'/my/salary-advances/{advance.id}/submit')
        self.assertEqual(advance.state, 'submitted')

    def test_prefilled_request_form(self):
        advance = self._new_advance()
        response = self.url_open(f'/my/salary-advances/{advance.id}/request-form')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'application/pdf')

    def test_cancel(self):
        advance = self._new_advance()
        self._post(f'/my/salary-advances/{advance.id}/cancel')
        self.assertEqual(advance.state, 'cancelled')

    def test_notice_period_warning(self):
        self._resign(self.employee, self.today + timedelta(days=60))
        self.assertIn('notice period', self.url_open('/my/salary-advances/new').text)
