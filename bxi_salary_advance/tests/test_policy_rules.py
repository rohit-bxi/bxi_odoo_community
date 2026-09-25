import base64
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import SalaryAdvanceCommon, make_pdf, month_start


@tagged('post_install', '-at_install')
class TestSalaryAdvancePolicyRules(SalaryAdvanceCommon):

    def _done_payslip(self, employee, month, net=50000.0):
        """A confirmed payslip of ``month`` paying ``net``, without running the payroll rules."""
        slip = self.env['hr.payslip'].create({
            'name': 'Confirmed payslip',
            'employee_id': employee.id,
            'date_from': month_start(month),
            'date_to': month_start(month, 1) - timedelta(days=1),
            'version_id': employee.version_id.id,
        })
        slip.write({'state': 'done', 'net_wage': net})
        return slip

    def _newcomer(self):
        return self._create_employee(
            'Newcomer', parent=self.manager, joined=fields.Date.today() - relativedelta(months=2))

    # ── Category I ───────────────────────────────────────────────────────
    def test_category_one_recovered_by_next_payroll(self):
        """Recovered by the payroll that pays the arrears, not the month after disbursement."""
        advance = self._disburse(self._approve(self._new_advance(category='non_processing', amount=20000)))
        self.assertEqual(advance.recovery_start, month_start(self.today))
        self.assertEqual(advance.installment_ids.mapped('due_date'), [month_start(self.today)])

    def test_category_one_skips_confirmed_payroll_month(self):
        self._done_payslip(self.employee, self.today, net=0.0)
        advance = self._disburse(self._approve(self._new_advance(category='non_processing', amount=20000)))
        self.assertEqual(advance.recovery_start, month_start(self.today, 1))

    def test_other_categories_recovered_month_after(self):
        advance = self._disburse(self._approve(self._new_advance(category='emergency', amount=30000)))
        self.assertEqual(advance.recovery_start, month_start(self.today, 1))

    def test_category_one_needs_unpaid_last_payroll(self):
        last_month = self.today - relativedelta(months=1)
        paid = self._done_payslip(self.employee, last_month)
        advance = self._new_advance(category='non_processing', amount=20000)
        with self.assertRaisesRegex(UserError, 'salary was processed'):
            advance.action_submit()
        # A zero payslip (joining formalities incomplete) means the salary was not processed.
        paid.net_wage = 0.0
        advance.action_submit()
        self.assertEqual(advance.state, 'submitted')

    def test_category_one_when_only_colleagues_were_paid(self):
        self._done_payslip(self.manager, self.today - relativedelta(months=1))
        advance = self._new_advance(category='non_processing', amount=20000)
        advance.action_submit()
        self.assertEqual(advance.state, 'submitted')

    def test_service_waived_for_joining_and_transfer(self):
        newcomer = self._newcomer()
        for reason in ('joining', 'transfer'):
            advance = self._new_advance(
                category='non_processing', amount=1000, employee=newcomer, nonprocessing_reason=reason)
            advance.action_submit()
            self.assertEqual(advance.state, 'submitted')
            advance.action_cancel()
        other = self._new_advance(
            category='non_processing', amount=1000, employee=newcomer, nonprocessing_reason='other')
        with self.assertRaisesRegex(UserError, '6 months'):
            other.action_submit()

    def test_service_required_when_configured(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_salary_advance.nonprocessing_require_service', True)
        advance = self._new_advance(
            category='non_processing', amount=1000, employee=self._newcomer(), nonprocessing_reason='joining')
        with self.assertRaisesRegex(UserError, '6 months'):
            advance.action_submit()

    # ── Full-time employees ──────────────────────────────────────────────
    def test_full_time_employees_only(self):
        self.employee.sudo().employee_type = 'contractor'
        advance = self._new_advance()
        with self.assertRaisesRegex(UserError, 'full-time'):
            advance.action_submit()
        self.env['ir.config_parameter'].sudo().set_param(
            'bxi_salary_advance.eligible_employee_types', 'employee,contractor')
        advance.action_submit()
        self.assertEqual(advance.state, 'submitted')

    # ── Outstanding advances ─────────────────────────────────────────────
    def test_outstanding_rule_for_emergency_only(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_salary_advance.outstanding_scope', 'emergency')
        self._approve(self._new_advance(category='emergency', amount=30000))
        housing = self._new_advance(category='housing', amount=50000)
        housing.action_submit()
        self.assertEqual(housing.state, 'submitted')
        emergency = self._new_advance(category='emergency', amount=10000)
        with self.assertRaisesRegex(UserError, 'not fully recovered'):
            emergency.action_submit()

    # ── Policy acknowledgement ───────────────────────────────────────────
    def test_policy_acknowledgement_required(self):
        policy = self.env['hr.company.policy'].create({'name': 'Salary Advance Policy', 'scope': 'all'})
        version = self.env['hr.company.policy.version'].create({
            'policy_id': policy.id,
            'document': base64.b64encode(make_pdf('Salary Advance Policy')),
            'filename': 'salary_advance_policy.pdf',
        })
        version.sudo().state = 'published'
        self.company.sa_policy_id = policy

        advance = self._new_advance()
        with self.assertRaisesRegex(UserError, 'acknowledge the Salary Advance Policy'):
            advance.action_submit()

        status = self.employee._sa_get_policy_status(create=True)
        self.assertEqual(status['policy'], policy)
        self.assertTrue(status['ack'])
        self.assertTrue(status['required'])
        status['ack'].sudo().state = 'acknowledged'
        advance.action_submit()
        self.assertEqual(advance.state, 'submitted')
