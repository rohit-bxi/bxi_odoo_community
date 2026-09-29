from unittest.mock import patch
from urllib.parse import unquote

from dateutil.relativedelta import relativedelta

from odoo.http import Request
from odoo.tests import HttpCase, tagged

from .common import REPORT_MODEL, TrainingTestMixin, make_pdf


@tagged('post_install', '-at_install')
class TestTrainingPortal(TrainingTestMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.startClassPatcher(patch(
            f'{REPORT_MODEL}._render_qweb_pdf', lambda *args, **kwargs: (make_pdf('Training document'), 'pdf'),
        ))
        cls._setup_training_data()

    def _login(self, employee):
        login = employee.user_id.login
        self.authenticate(login, login)

    def _post(self, url, data=None, files=None):
        data = dict(data or {}, csrf_token=Request.csrf_token(self))
        response = self.url_open(url, data=data, files=files, allow_redirects=False)
        self.env.invalidate_all()  # the request ran in the server; drop the stale cache
        return response

    def test_pages_render(self):
        training = self._nominate(self._new_training())
        self._login(self.employee)
        for url in ('/my', '/my/trainings', '/my/training-agreements', f'/my/trainings/{training.id}'):
            response = self.url_open(url)
            self.assertEqual(response.status_code, 200, url)
        self.assertIn('/my/trainings', self.url_open('/my').text)
        self.assertIn(training.name, self.url_open('/my/trainings').text)
        self.assertIn('Review and Sign', self.url_open(f'/my/trainings/{training.id}').text)
        # Only Department Heads nominate.
        self.assertEqual(self.url_open('/my/trainings/nominate').status_code, 404)

    def test_other_employee_training_not_found(self):
        other = self._new_training(employee=self.manager)
        self._login(self.employee)
        self.assertEqual(self.url_open(f'/my/trainings/{other.id}').status_code, 404)
        self.assertEqual(self.url_open('/my/trainings/999999').status_code, 404)

    def test_department_head_nominates(self):
        self._login(self.head)
        self.assertEqual(self.url_open('/my/trainings/nominate').status_code, 200)
        start = self.today + relativedelta(days=30)
        response = self._post('/my/trainings/nominate', {
            'employee_id': str(self.employee.id), 'training_name': 'AWS Architect Bootcamp',
            'provider': 'Cloud Academy', 'location': 'Hyderabad', 'scope': 'domestic',
            'start_date': str(start), 'end_date': str(start + relativedelta(days=4)),
            'purpose': 'Migration project', 'submit_now': '1',
            'category[]': ['fee', 'lodging'], 'description[]': ['Course', 'Hotel'],
            'paid_by[]': ['company', 'employee'], 'amount[]': ['35000', '15000'],
        })
        self.assertEqual(response.status_code, 303)
        training = self.env['bxi.training.request'].search([('employee_id', '=', self.employee.id)])
        self.assertEqual(training.state, 'hr_review')
        self.assertEqual(training.nominated_by_id, self.head)
        self.assertEqual(training.estimated_cost, 50000)
        self.assertEqual(training.provider_id.name, 'Cloud Academy')

    def test_nomination_error_keeps_nothing(self):
        self._login(self.head)
        start = self.today + relativedelta(days=5)
        response = self._post('/my/trainings/nominate', {
            'employee_id': str(self.employee.id), 'training_name': 'Late course', 'location': 'Pune',
            'start_date': str(start), 'end_date': str(start), 'purpose': 'x', 'submit_now': '1',
            'category[]': ['fee'], 'description[]': [''], 'paid_by[]': ['company'], 'amount[]': ['1000'],
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('20 days', response.text)
        self.assertFalse(self.env['bxi.training.request'].search([('employee_id', '=', self.employee.id)]))

    def test_upload_executed_agreement(self):
        training = self._nominate(self._new_training())
        training._on_form_signed()
        agreement = training.agreement_id
        self._login(self.employee)
        download = self.url_open(f'/my/trainings/{training.id}/agreement/{agreement.id}/download')
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.headers['Content-Type'], 'application/pdf')
        url = f'/my/trainings/{training.id}/agreement/{agreement.id}'
        response = self._post(url, {'stamp_paper_no': 'KA-1', 'stamp_paper_value': '100'})
        self.assertIn('Please provide', unquote(response.headers['Location']))
        response = self._post(url, {
            'stamp_paper_no': 'KA-1', 'stamp_paper_value': '100', 'stamp_paper_date': str(self.today),
            'witness1_name': 'A', 'witness2_name': 'B', 'notary_name': 'N', 'notarised_date': str(self.today),
        }, files={'scan': ('agreement.pdf', make_pdf('Executed'), 'application/pdf')})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(agreement.state, 'submitted')
        self.assertEqual(len(agreement.executed_scan_ids), 1)

    def test_submit_claim(self):
        training = self._ready(self._new_training(fee=10000, lodging=5000))
        self._complete(training)
        self._login(self.employee)
        response = self._post(f'/my/trainings/{training.id}/claim', {
            'product_id[]': [str(self.lodging_product.id), str(self.fee_product.id)],
            'amount[]': ['4500', ''], 'description[]': ['Hotel', ''],
        }, files=[('receipt[]', ('hotel.pdf', make_pdf('Hotel'), 'application/pdf')),
                  ('receipt[]', ('empty.pdf', b'', 'application/pdf'))])
        self.assertEqual(response.status_code, 303)
        self.assertEqual(training.state, 'claim_approval')
        self.assertEqual(training.claim_total, 4500)
        self.assertEqual(training.expense_ids.product_id, self.lodging_product)

    def test_pages_for_each_step(self):
        """The training page renders the agreement, claim and approval sections."""
        training = self._nominate(self._new_training())
        training._on_form_signed()
        self._login(self.employee)
        page = self.url_open(f'/my/trainings/{training.id}').text
        self.assertIn('stamp paper', page)
        self.assertIn('Submit to HR', page)

        self._execute_agreement(training)
        self._complete(training)
        page = self.url_open(f'/my/trainings/{training.id}').text
        self.assertIn('Claim the Training Cost', page)
        self.assertIn(self.fee_product.name, page)
        self.assertIn(training.agreement_id.name, self.url_open('/my/training-agreements').text)

        self._add_claim_line(training, self.lodging_product, 4000)
        training.with_user(self.employee.user_id).action_submit_claim()
        page = self.url_open(f'/my/trainings/{training.id}').text
        self.assertIn('Claim Approval', page)
        self.assertIn('Reporting Manager', page)

    def test_department_head_sees_and_submits_draft(self):
        training = self._new_training()
        self._login(self.head)
        self.assertIn(training.name, self.url_open('/my/trainings').text)
        response = self._post(f'/my/trainings/{training.id}/submit')
        self.assertEqual(response.status_code, 303)
        self.assertEqual(training.state, 'hr_review')
        # The employee cannot submit their own nomination.
        other = self._new_training()
        self._login(self.employee)
        self.assertEqual(self._post(f'/my/trainings/{other.id}/submit').status_code, 404)
        self.assertEqual(other.state, 'draft')
