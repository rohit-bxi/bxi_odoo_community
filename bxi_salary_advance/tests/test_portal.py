from datetime import timedelta
from urllib.parse import unquote

from odoo.http import Request
from odoo.tests import HttpCase, new_test_user, tagged

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

    def test_no_access_employee_uses_portal_for_own_advances(self):
        """Salary Advance access "No" is a regular employee: own advances only."""
        self.assertFalse(self.employee.user_id.has_group('bxi_salary_advance.group_salary_advance_hr'))
        self.assertIn('/my/salary-advances', self.url_open('/my').text)
        response = self._post('/my/salary-advances/new', {
            'category': 'emergency', 'emergency_type': 'birth', 'amount_requested': '30000',
        })
        self.assertEqual(response.status_code, 303)
        own = self.env['bxi.salary.advance'].search([('employee_id', '=', self.employee.id)])
        self.assertEqual(len(own), 1)
        other = self._new_advance(employee=self.manager)
        page = self.url_open('/my/salary-advances').text
        self.assertIn(own.name, page)
        self.assertNotIn(other.name, page)

    def test_same_work_email_on_other_employee_is_not_matched(self):
        """An employee of another user sharing the work email (sorted first by
        name) must not be taken as the current user's employee."""
        admin = self._create_employee('Adminstrator')
        admin.work_email = self.employee.work_email
        admin_advance = self._new_advance(employee=admin)
        own = self._new_advance(amount=30000)

        page = self.url_open('/my/salary-advances').text
        self.assertIn(own.name, page)
        self.assertNotIn(admin_advance.name, page)
        self.assertEqual(self.url_open(f'/my/salary-advances/{admin_advance.id}').status_code, 404)
        self.assertEqual(self.url_open(f'/my/salary-advances/{admin_advance.id}/edit').status_code, 404)

    def test_email_fallback_only_for_unlinked_employee(self):
        user = new_test_user(self.env, login='sa_test_unlinked', groups='base.group_user',
                             email='sa_test_unlinked@example.com')
        linked_elsewhere = self._create_employee('Linked Elsewhere')
        linked_elsewhere.work_email = user.email
        self._new_advance(employee=linked_elsewhere)
        self.authenticate(user.login, user.login)
        self.assertIn('No employee record is linked', self.url_open('/my/salary-advances').text)

        self.env['hr.employee'].create({'name': 'Unlinked', 'work_email': user.email})
        self.assertNotIn('No employee record is linked', self.url_open('/my/salary-advances').text)

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

    def test_update_draft(self):
        advance = self._new_advance(amount=30000)
        self.assertIn(f'/my/salary-advances/{advance.id}/edit', self.url_open('/my/salary-advances').text)
        self.assertIn(f'/my/salary-advances/{advance.id}/edit', self.url_open(f'/my/salary-advances/{advance.id}').text)

        page = self.url_open(f'/my/salary-advances/{advance.id}/edit')
        self.assertEqual(page.status_code, 200)
        self.assertIn(f'Update {advance.name}', page.text)
        self.assertIn('30000', page.text)

        # Switch category: the emergency type of the old category is cleared.
        response = self._post(f'/my/salary-advances/{advance.id}/edit', {
            'category': 'non_processing', 'nonprocessing_reason': 'joining', 'emergency_type': 'medical',
            'amount_requested': '40000', 'reason': 'Joining formalities pending',
        }, files={'request_form': ('second.pdf', make_pdf('Second'), 'application/pdf')})
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers['Location'].endswith(f'/my/salary-advances/{advance.id}'))
        self.assertEqual(advance.state, 'draft')
        self.assertEqual(advance.category, 'non_processing')
        self.assertEqual(advance.nonprocessing_reason, 'joining')
        self.assertFalse(advance.emergency_type)
        self.assertEqual(advance.amount_requested, 40000)
        self.assertEqual(advance.reason, 'Joining formalities pending')
        self.assertEqual(len(advance.request_form_ids), 2)

    def test_update_and_submit(self):
        advance = self._new_advance(amount=30000)
        self._post(f'/my/salary-advances/{advance.id}/edit', {
            'category': 'emergency', 'emergency_type': 'birth', 'amount_requested': '35000', 'submit_now': '1',
        })
        self.assertEqual(advance.state, 'submitted')
        self.assertEqual(advance.amount_requested, 35000)
        self.assertEqual(advance.emergency_type, 'birth')

    def test_update_error_keeps_draft_unchanged(self):
        advance = self._new_advance(amount=30000)
        response = self._post(f'/my/salary-advances/{advance.id}/edit', {
            'category': 'emergency', 'emergency_type': 'birth', 'amount_requested': '70000', 'submit_now': '1',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('75%', response.text)
        self.assertEqual(advance.state, 'draft')
        self.assertEqual(advance.amount_requested, 30000)

    def test_update_only_own_draft(self):
        advance = self._new_advance(amount=30000)
        self._post(f'/my/salary-advances/{advance.id}/submit')
        self.assertEqual(advance.state, 'submitted')
        self.assertNotIn(f'/my/salary-advances/{advance.id}/edit', self.url_open('/my/salary-advances').text)

        response = self.url_open(f'/my/salary-advances/{advance.id}/edit', allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self._post(f'/my/salary-advances/{advance.id}/edit', {
            'category': 'emergency', 'emergency_type': 'birth', 'amount_requested': '1000',
        })
        self.assertEqual(advance.amount_requested, 30000)

        other = self._new_advance(employee=self.manager)
        self.assertEqual(self.url_open(f'/my/salary-advances/{other.id}/edit').status_code, 404)

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
