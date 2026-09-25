from datetime import timedelta
from urllib.parse import unquote

from odoo.http import Request
from odoo.tests import HttpCase, new_test_user, tagged

from .common import CertificationTestMixin, make_pdf


@tagged('post_install', '-at_install')
class TestCertificationPortal(CertificationTestMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_certification_data()

    def setUp(self):
        super().setUp()
        login = self.engineer.user_id.login
        self.authenticate(login, login)

    def _post(self, url, data=None, files=None):
        data = dict(data or {}, csrf_token=Request.csrf_token(self))
        response = self.url_open(url, data=data, files=files, allow_redirects=False)
        self.env.invalidate_all()  # the request ran in the server; drop the stale cache
        return response

    def _approved_request(self):
        return self._pre_approve(self._new_request())

    # ── Pages ────────────────────────────────────────────────────────────
    def test_pages_render(self):
        request = self._approved_request()
        for url in ('/my', '/my/certifications', '/my/certifications/new',
                    '/my/certifications/inclusion', f'/my/certifications/{request.id}'):
            response = self.url_open(url)
            self.assertEqual(response.status_code, 200, url)
        self.assertIn('/my/certifications', self.url_open('/my').text)
        self.assertIn(request.name, self.url_open('/my/certifications').text)
        self.assertIn('Claim Reimbursement', self.url_open(f'/my/certifications/{request.id}').text)

    def test_other_employees_request_is_not_found(self):
        other = self._new_request(employee=self.manager)
        self.assertEqual(self.url_open(f'/my/certifications/{other.id}').status_code, 404)
        self.assertEqual(self.url_open('/my/certifications/999999').status_code, 404)

    def test_error_is_displayed(self):
        request = self._approved_request()
        response = self.url_open(f'/my/certifications/{request.id}?error=Something%20went%20wrong')
        self.assertIn('Something went wrong', response.text)

    # ── New request ──────────────────────────────────────────────────────
    def test_new_request(self):
        response = self._post('/my/certifications/new', {
            'certification_id': self.certification.id,
            'estimated_cost': '4000',
            'planned_exam_date': str(self.today + timedelta(days=20)),
            'cost_centre_ack': 'on',
        }, files={'approval_email': ('approval.pdf', make_pdf('Approval'), 'application/pdf')})
        self.assertEqual(response.status_code, 303)
        request = self.env['bxi.certification.request'].search([('employee_id', '=', self.engineer.id)])
        self.assertEqual(request.state, 'rm_approval')
        self.assertEqual(request.estimated_cost, 4000)
        self.assertEqual(request.pre_approval_attachment_ids.name, 'approval.pdf')
        self.assertTrue(response.headers['Location'].endswith(f'/my/certifications/{request.id}'))

    def test_new_request_not_in_list(self):
        self._post('/my/certifications/new', {
            'certification_name': 'Unlisted Cert', 'certifying_body': 'Body', 'cost_centre_ack': 'on',
        })
        request = self.env['bxi.certification.request'].search([('employee_id', '=', self.engineer.id)])
        self.assertFalse(request.is_on_approved_list)
        self.assertEqual(request.certification_name, 'Unlisted Cert')

    def test_new_request_error_rolls_back(self):
        response = self._post('/my/certifications/new', {'certification_id': self.certification.id})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Reporting Manager', response.text)  # cost centre acknowledgement missing
        self.assertFalse(self.env['bxi.certification.request'].search([('employee_id', '=', self.engineer.id)]))

    # ── Claim ────────────────────────────────────────────────────────────
    def _claim_data(self, days_ago=5, **extra):
        data = {
            'exam_clear_date': str(self.today - timedelta(days=days_ago)),
            'attempt_passed': 'on',
            'product_id[]': [self.exam_fee.id, self.dd_charges.id, self.courier.id],
            'description[]': ['Exam fee', '', ''],
            'amount[]': ['4000', '', '300'],
        }
        data.update(extra)
        return data

    def _claim_files(self):
        return [
            ('certificate', ('certificate.pdf', make_pdf('Certificate'), 'application/pdf')),
            ('receipt[]', ('fee.pdf', make_pdf('Fee receipt'), 'application/pdf')),
            ('receipt[]', ('', b'', 'application/octet-stream')),
            ('receipt[]', ('courier.pdf', make_pdf('Courier receipt'), 'application/pdf')),
        ]

    def test_submit_claim(self):
        request = self._approved_request()
        response = self._post(f'/my/certifications/{request.id}/claim', self._claim_data(), files=self._claim_files())
        self.assertEqual(response.status_code, 303)
        self.assertNotIn('error=', response.headers['Location'])
        self.assertEqual(request.state, 'claim_approval')
        self.assertEqual(request.claim_total, 4300)
        self.assertEqual(request.certificate_attachment_ids.name, 'certificate.pdf')
        fee = request.expense_ids.filtered(lambda exp: exp.product_id == self.exam_fee)
        courier = request.expense_ids.filtered(lambda exp: exp.product_id == self.courier)
        self.assertEqual(fee.name, 'Exam fee')
        self.assertEqual(courier.name, self.courier.name, "Empty description falls back to the category")
        self.assertEqual(fee.message_main_attachment_id.name, 'fee.pdf')
        self.assertEqual(courier.message_main_attachment_id.name, 'courier.pdf',
                         "Receipts stay aligned with their lines when a row is left empty")
        self.assertFalse(request.expense_ids.filtered(lambda exp: exp.product_id == self.dd_charges))

    def test_claim_error_is_shown_and_rolled_back(self):
        self.band4.cost_center_id = False
        request = self._approved_request()
        response = self._post(f'/my/certifications/{request.id}/claim', self._claim_data(), files=self._claim_files())
        self.assertEqual(response.status_code, 303)
        self.assertIn('No cost centre', unquote(response.headers['Location']))
        self.assertEqual(request.state, 'approved')
        self.assertFalse(request.expense_ids)

    def test_claim_rejects_other_categories(self):
        request = self._approved_request()
        data = self._claim_data(**{'product_id[]': [self.meals.id], 'description[]': ['Lunch'], 'amount[]': ['100']})
        response = self._post(f'/my/certifications/{request.id}/claim', data, files=self._claim_files()[:1])
        self.assertIn('Only certification expense categories', unquote(response.headers['Location']))
        self.assertFalse(request.expense_ids)

    def test_claim_on_request_not_approved(self):
        request = self._new_request()
        request.action_submit()
        response = self._post(f'/my/certifications/{request.id}/claim', self._claim_data(), files=self._claim_files())
        self.assertEqual(response.status_code, 303)
        self.assertEqual(request.state, 'rm_approval')
        self.assertFalse(request.expense_ids)

    def test_cannot_claim_on_other_employees_request(self):
        other = self._pre_approve(self._new_request(employee=self.manager))
        response = self._post(f'/my/certifications/{other.id}/claim', self._claim_data(), files=self._claim_files())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(other.state, 'approved')

    # ── Cancel ───────────────────────────────────────────────────────────
    def test_cancel(self):
        request = self._approved_request()
        response = self._post(f'/my/certifications/{request.id}/cancel')
        self.assertEqual(response.status_code, 303)
        self.assertEqual(request.state, 'cancelled')

    def test_cancel_after_claim_shows_error(self):
        request = self._claim(self._approved_request(), [1000])
        response = self._post(f'/my/certifications/{request.id}/cancel')
        self.assertIn('error=', response.headers['Location'])
        self.assertEqual(request.state, 'claim_approval')

    # ── Inclusion request ────────────────────────────────────────────────
    def test_inclusion_request(self):
        response = self._post('/my/certifications/inclusion', {
            'certification_name': 'Terraform Associate', 'version_exam_no': '003', 'certifying_body': 'HashiCorp',
            'area': 'Infrastructure', 'cost': '70', 'currency_id': self.env.ref('base.USD').id,
            'lob_id': self.lob.id, 'website': 'https://www.hashicorp.com', 'is_du_specific': 'y',
            'information': 'IaC', 'business_case': 'Client projects',
        })
        self.assertEqual(response.status_code, 303)
        inclusion = self.env['bxi.certification.inclusion'].search([('employee_id', '=', self.engineer.id)])
        self.assertEqual(inclusion.state, 'submitted')
        self.assertEqual(inclusion.is_du_specific, 'y')
        self.assertTrue(inclusion.deadline_date)

    def test_inclusion_request_error(self):
        response = self._post('/my/certifications/inclusion', {'certification_name': 'Incomplete'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Please fill in', response.text)
        self.assertFalse(self.env['bxi.certification.inclusion'].search([('employee_id', '=', self.engineer.id)]))

    # ── Agreements on the portal ─────────────────────────────────────────
    def test_agreement_listed(self):
        agreement = self._create_agreement(state='active')
        self.assertIn(agreement.name, self.url_open('/my/certifications').text)

    def test_user_without_employee(self):
        new_test_user(self.env, login='cert_test_no_employee', groups='base.group_user')
        self.authenticate('cert_test_no_employee', 'cert_test_no_employee')
        self.assertIn('No employee record', self.url_open('/my/certifications').text)
        self.assertEqual(self.url_open('/my/certifications/new').status_code, 404)
