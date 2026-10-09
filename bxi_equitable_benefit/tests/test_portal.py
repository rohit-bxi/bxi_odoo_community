from datetime import date

from odoo.http import Request
from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestEquitableBenefitPortal(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('bxi_equitable_benefit.fy_start_month', 4)
        cls.reviewer = new_test_user(
            cls.env, login='eb_portal_reviewer',
            groups='base.group_user,bxi_equitable_benefit.group_eb_revenue_assurance')
        cls.user = new_test_user(cls.env, login='eb_portal_employee', groups='base.group_portal')
        cls.other_user = new_test_user(cls.env, login='eb_portal_other', groups='base.group_portal')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Aman', 'user_id': cls.user.id, 'date_version': date(2020, 1, 1),
        })
        cls.other = cls.env['hr.employee'].create({
            'name': 'Neha', 'user_id': cls.other_user.id, 'date_version': date(2020, 1, 1),
        })
        cls.employee.eb_annual_component_a = 500000
        cls.pattern_6 = cls.env.ref('bxi_equitable_benefit.work_pattern_6_day')
        cls.project = cls.env['project.project'].create({'name': 'Client Rollout'})
        cls.project.message_subscribe(partner_ids=cls.user.partner_id.ids)

    def _post(self, url, data, files=None):
        data = dict(data, csrf_token=Request.csrf_token(self))
        response = self.url_open(url, data=data, files=files, allow_redirects=False)
        self.env.invalidate_all()
        return response

    def _assignments(self):
        return self.env['bxi.eb.assignment'].search([('employee_id', '=', self.employee.id)])

    def test_pages_render(self):
        self.authenticate(self.user.login, self.user.login)
        for url in ('/my', '/my/equitable-benefit', '/my/equitable-benefit/pattern/new'):
            self.assertEqual(self.url_open(url).status_code, 200, url)
        self.assertIn('/my/equitable-benefit', self.url_open('/my').text)
        page = self.url_open('/my/equitable-benefit/pattern/new').text
        self.assertIn('Client Rollout', page)
        self.assertIn('9.6%', page)

    def test_declare_work_pattern(self):
        self.authenticate(self.user.login, self.user.login)
        response = self._post('/my/equitable-benefit/pattern/new', {
            'work_pattern_id': str(self.pattern_6.id), 'work_category': 'client', 'deployment': 'onsite',
            'date_from': '2025-04-01', 'project_ids': str(self.project.id),
        }, files={'documents': ('sow.txt', b'Client SOW: six days a week', 'text/plain')})
        self.assertEqual(response.status_code, 303)
        assignment = self._assignments()
        self.assertEqual(assignment.state, 'submitted')
        self.assertEqual(assignment.project_ids, self.project)
        self.assertEqual(len(assignment.requirement_attachment_ids), 1)
        self.assertIn(assignment.name, self.url_open('/my/equitable-benefit').text)

    def test_policy_error_shown_and_nothing_saved(self):
        self.authenticate(self.user.login, self.user.login)
        response = self._post('/my/equitable-benefit/pattern/new', {
            'work_pattern_id': str(self.pattern_6.id), 'work_category': 'client', 'deployment': 'onsite',
            'date_from': '2025-04-01',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('documented', response.text)
        self.assertFalse(self._assignments())

    def test_withdraw(self):
        self.authenticate(self.user.login, self.user.login)
        self._post('/my/equitable-benefit/pattern/new', {
            'work_pattern_id': str(self.pattern_6.id), 'work_category': 'client', 'deployment': 'onsite',
            'date_from': '2025-04-01', 'justification': 'Client SOW',
        })
        assignment = self._assignments()
        self._post(f'/my/equitable-benefit/pattern/{assignment.id}/withdraw', {})
        self.assertEqual(assignment.state, 'cancelled')
        # Not someone else's.
        self.authenticate(self.other_user.login, self.other_user.login)
        assignment.state = 'submitted'
        response = self._post(f'/my/equitable-benefit/pattern/{assignment.id}/withdraw', {})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(assignment.state, 'submitted')

    def test_statement_of_approved_payout_only(self):
        payout = self.env['bxi.eb.payout'].create({
            'employee_id': self.employee.id, 'fy_start': date(2025, 4, 1), 'fy_end': date(2026, 3, 31),
            'period_end': date(2026, 3, 31),
        })
        url = f'/my/equitable-benefit/payout/{payout.id}/statement'
        self.authenticate(self.user.login, self.user.login)
        self.assertEqual(self.url_open(url).status_code, 404)
        self.assertNotIn(payout.fy_name, self.url_open('/my/equitable-benefit').text)
        payout.state = 'approved'
        self.assertEqual(self.url_open(url).status_code, 200)
        self.assertIn(payout.fy_name, self.url_open('/my/equitable-benefit').text)
        self.authenticate(self.other_user.login, self.other_user.login)
        self.assertEqual(self.url_open(url).status_code, 404)
