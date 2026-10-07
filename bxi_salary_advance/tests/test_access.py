from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from .common import SalaryAdvanceTestMixin


@tagged('post_install', '-at_install')
class TestSalaryAdvanceAccess(SalaryAdvanceTestMixin, TransactionCase):
    """Employees without Salary Advance access ("No") create and see only their
    own advances; a Reporting Manager also sees and approves the team's."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_salary_advance_data()
        cls.colleague = cls._create_employee('Colleague', parent=cls.manager)

    def _vals(self, employee):
        return {'employee_id': employee.id, 'category': 'emergency', 'emergency_type': 'medical',
                'amount_requested': 1000}

    def test_no_access_creates_and_sees_only_own(self):
        own = self._new_advance()
        other = self._new_advance(employee=self.colleague)
        Advance = self.env['bxi.salary.advance'].with_user(self.employee.user_id)

        self.assertEqual(Advance.search([]), own)
        own.with_user(self.employee.user_id).read(['name'])
        with self.assertRaises(AccessError):
            other.with_user(self.employee.user_id).read(['name'])
        with self.assertRaises(AccessError):
            Advance.create(self._vals(self.colleague))
        with self.assertRaises(AccessError):
            other.with_user(self.employee.user_id).write({'reason': 'Not mine'})

    def test_manager_sees_and_approves_team_but_cannot_create_for_them(self):
        advance = self._new_advance()
        advance.action_submit()
        Advance = self.env['bxi.salary.advance'].with_user(self.manager.user_id)

        self.assertIn(advance, Advance.search([]))
        advance.with_user(self.manager.user_id).action_rm_approve()
        self.assertEqual(advance.state, 'hr_review')

        with self.assertRaises(AccessError):
            Advance.create(self._vals(self.employee))
        Advance.create(self._vals(self.manager))  # own request is allowed

    def test_emi_lines_only_own_or_team(self):
        advance = self._disburse(self._approve(self._new_advance()))
        self.assertTrue(advance.installment_ids)
        Installment = self.env['bxi.salary.advance.installment']
        self.assertFalse(Installment.with_user(self.colleague.user_id).search(
            [('advance_id', '=', advance.id)]))
        self.assertEqual(
            Installment.with_user(self.employee.user_id).search([('advance_id', '=', advance.id)]),
            advance.installment_ids)

    def test_hr_sees_all(self):
        own = self._new_advance()
        other = self._new_advance(employee=self.colleague)
        self.assertEqual(self.env['bxi.salary.advance'].with_user(self.hr_user).search([]) & (own | other),
                         own | other)
