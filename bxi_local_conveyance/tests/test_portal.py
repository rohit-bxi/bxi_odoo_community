from odoo.http import Request
from odoo.tests import HttpCase, tagged

from .common import ConveyanceTestMixin


@tagged('post_install', '-at_install')
class TestConveyancePortal(ConveyanceTestMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_conveyance_data()

    def _login(self, employee):
        login = employee.user_id.login
        self.authenticate(login, login)

    def _post(self, data, files=None):
        data = dict(data, csrf_token=Request.csrf_token(self))
        response = self.url_open('/my/conveyance/new', data=data, files=files, allow_redirects=False)
        self.env.invalidate_all()  # the request ran in the server; drop the stale cache
        return response

    def _claims(self, employee):
        return self.env['hr.expense'].search([('employee_id', '=', employee.id), ('conveyance_kind', '!=', False)])

    def test_pages_render(self):
        self._login(self.employee)
        for url in ('/my', '/my/conveyance', '/my/conveyance/new'):
            self.assertEqual(self.url_open(url).status_code, 200, url)
        self.assertIn('/my/conveyance', self.url_open('/my').text)
        page = self.url_open('/my/conveyance/new').text
        self.assertIn('TP2', page)
        # Food is for the Sales Team only.
        self.assertNotIn(self.product_food.name, page)
        self._login(self.salesman)
        self.assertIn(self.product_food.name, self.url_open('/my/conveyance/new').text)

    def test_submit_personal_vehicle(self):
        self._login(self.employee)
        response = self._post({
            'product_id': str(self.product_4w.id), 'date': str(self.workday), 'name': 'Client visit',
            'purpose': 'client_visit', 'from': 'Saket', 'to': 'Client, Nehru Place', 'distance': '14',
            'within_city': 'on',
        })
        self.assertEqual(response.status_code, 303)
        claim = self._claims(self.employee)
        self.assertEqual(claim.state, 'conveyance_approval')
        self.assertEqual(claim.total_amount, 70.0)
        self.assertEqual(claim.conveyance_approval_line_ids.approver_user_id, self.manager.user_id)
        self.assertIn('Client visit', self.url_open('/my/conveyance').text)

    def test_submit_auto_with_bill(self):
        self._login(self.junior)
        response = self._post({
            'product_id': str(self.product_auto.id), 'date': str(self.workday), 'purpose': 'official_visit',
            'from': 'Saket', 'to': 'Bank', 'amount': '1200', 'within_city': 'on',
        }, files={'receipt': ('bill.txt', b'Auto bill 1200', 'text/plain')})
        self.assertEqual(response.status_code, 303)
        claim = self._claims(self.junior)
        self.assertEqual(claim.total_amount, 1200)
        self.assertEqual(claim.nb_attachment, 1)
        self.assertEqual(claim.conveyance_approval_line_ids.mapped('role'), ['rm', 'hr'])

    def test_policy_error_shown_and_nothing_saved(self):
        self._login(self.employee)
        response = self._post({
            'product_id': str(self.product_taxi.id), 'date': str(self.workday), 'purpose': 'client_visit',
            'from': 'Saket', 'to': 'Client', 'amount': '400', 'within_city': 'on',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('attach the bill', response.text)
        self.assertFalse(self._claims(self.employee))

    def test_submit_transfer_drive(self):
        self._login(self.employee)
        self.assertNotIn(self.product_transfer_4w.name, self.url_open('/my/conveyance/new').text)
        transfer = self.env['bxi.conveyance.transfer'].create({
            'employee_id': self.employee.id, 'from_city': 'Delhi', 'to_city': 'Jaipur',
            'transfer_date': self.workday, 'vehicle_option': 'drive',
        })
        self.assertIn(self.product_transfer_4w.name, self.url_open('/my/conveyance/new').text)
        response = self._post({
            'product_id': str(self.product_transfer_4w.id), 'date': str(self.workday),
            'transfer_id': str(transfer.id), 'distance': '280',
        })
        self.assertEqual(response.status_code, 303)
        claim = self._claims(self.employee)
        self.assertEqual(claim.conveyance_transfer_id, transfer)
        self.assertEqual(claim.total_amount, 1400.0)
        self.assertEqual(claim.state, 'conveyance_approval')
