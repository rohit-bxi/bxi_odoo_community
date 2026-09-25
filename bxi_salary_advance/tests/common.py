import io
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from reportlab.pdfgen import canvas

from odoo import fields
from odoo.tests import TransactionCase, new_test_user

REPORT_MODEL = 'odoo.addons.base.models.ir_actions_report.IrActionsReport'


def make_pdf(text='Test document'):
    """Return the bytes of a small, valid one-page PDF."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(100, 750, text)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


class SalaryAdvanceTestMixin:
    """An India company, an employee with a Reporting Manager and the policy defaults.

    The employee's monthly gross is 80,000 (basic 40,000 + HRA 16,000 + allowance 24,000),
    so the 75% limit is 60,000."""

    @classmethod
    def _setup_salary_advance_data(cls):
        # The tests must not depend on the configuration of the database they run on.
        cls.company = cls.env.company
        cls.company.country_id = cls.env.ref('base.in')
        set_param = cls.env['ir.config_parameter'].sudo().set_param
        for key, value in {
            'limit_percent': 75, 'salary_basis': 'gross', 'min_service_months': 6,
            'emergency_installments': 3, 'housing_tenancies': '6,12', 'housing_limit_percent': 0,
            'request_form_optional': False, 'hr_sla_days': 7, 'rm_reminder_days': 2,
            'perquisite_threshold': 20000, 'eligible_employee_types': 'employee,worker',
            'outstanding_scope': 'all', 'nonprocessing_require_service': False,
        }.items():
            set_param(f'bxi_salary_advance.{key}', value)
        cls.company.write({
            'sa_hr_user_id': False, 'sa_finance_user_id': False, 'sa_geo_hr_head_id': False,
            'sa_advance_account_id': False, 'sa_recovery_account_id': False,
            'sa_disbursement_journal_id': False, 'sa_recovery_journal_id': False, 'sa_policy_id': False,
        })
        cls.today = fields.Date.today()

        cls.hr_user = new_test_user(
            cls.env, login='sa_test_hr', name='HR Officer',
            groups='base.group_user,bxi_salary_advance.group_salary_advance_hr')
        cls.finance_user = new_test_user(
            cls.env, login='sa_test_finance', name='Finance User',
            groups='base.group_user,bxi_salary_advance.group_salary_advance_finance')
        cls.manager = cls._create_employee('Manager')
        cls.employee = cls._create_employee('Engineer', parent=cls.manager)
        cls.hr_head = cls._create_employee('LoB HR Head')
        cls.lob = cls.env['bxi.line.of.business'].create({
            'name': 'Test Digital', 'code': 'SA-TEST', 'hr_head_id': cls.hr_head.id,
        })
        cls.employee.lob_id = cls.lob
        cls.vendor = cls.env['res.partner'].create({'name': 'Housing Partner Ltd'})

    @classmethod
    def _create_employee(cls, name, parent=None, joined=None, basic=40000, hra=16000, allowance=24000):
        login = 'sa_test_' + name.lower().replace(' ', '_')
        user = new_test_user(cls.env, login=login, groups='base.group_user',
                             email=f"{login}@example.com", name=name)
        employee = cls.env['hr.employee'].create({
            'name': name,
            'user_id': user.id,
            'parent_id': parent.id if parent else False,
            'work_email': f"{login}@example.com",
            'emp_date_of_joining': joined or fields.Date.today() - relativedelta(years=2),
            'l10n_in_fixed_allowance': allowance,
        })
        employee.version_id.write({'wage': basic, 'hra': hra})
        return employee

    @classmethod
    def _setup_accounting(cls):
        Account = cls.env['account.account']
        cls.advance_account = Account.create({
            'code': 'SA1301', 'name': 'Employee Advances', 'account_type': 'asset_receivable', 'reconcile': True})
        cls.salary_payable = Account.create({
            'code': 'SA2101', 'name': 'Salary Payable', 'account_type': 'liability_current', 'reconcile': True})
        cls.vendor_payable = Account.create({
            'code': 'SA2111', 'name': 'Vendors', 'account_type': 'liability_payable', 'reconcile': True})
        bank_account = Account.create({'code': 'SA1101', 'name': 'Bank', 'account_type': 'asset_cash'})
        cls.bank_journal = cls.env['account.journal'].create({
            'name': 'SA Bank', 'type': 'bank', 'code': 'SABK', 'default_account_id': bank_account.id,
        })
        cls.misc_journal = cls.env['account.journal'].create({'name': 'SA Payroll', 'type': 'general', 'code': 'SAPR'})
        cls.vendor.with_company(cls.company).property_account_payable_id = cls.vendor_payable
        cls.company.write({
            'sa_advance_account_id': cls.advance_account.id,
            'sa_disbursement_journal_id': cls.bank_journal.id,
            'sa_recovery_account_id': cls.salary_payable.id,
            'sa_recovery_journal_id': cls.misc_journal.id,
        })

    # ── Workflow helpers ─────────────────────────────────────────────────
    def _new_advance(self, category='emergency', amount=45000, employee=None, **vals):
        employee_user = (employee or self.employee).user_id
        # Uploaded by the employee, like on the portal: other users' files are not readable.
        pdf = self.env['ir.attachment'].with_user(employee_user).create({
            'name': 'signed.pdf', 'raw': make_pdf('Signed form')})
        values = {
            'employee_id': (employee or self.employee).id,
            'category': category,
            'amount_requested': amount,
            'request_form_ids': [(6, 0, pdf.ids)],
        }
        if category == 'emergency':
            values['emergency_type'] = 'medical'
        elif category == 'non_processing':
            values['nonprocessing_reason'] = 'joining'
        elif category == 'housing':
            values.update(tenancy_months=12, rental_agreement_ids=[(6, 0, pdf.ids)])
        values.update(vals)
        return self.env['bxi.salary.advance'].with_user(employee_user).create(values)

    def _approve(self, advance):
        advance.action_submit()
        advance.with_user(self.manager.user_id).action_rm_approve()
        hr_advance = advance.with_user(self.hr_user)
        if advance.category == 'housing' and not hr_advance.vendor_partner_id:
            hr_advance.vendor_partner_id = self.vendor
        hr_advance.action_hr_approve()
        return advance.with_env(self.env)

    def _disburse(self, advance, when=None, create_entry=None):
        wizard = self.env['bxi.salary.advance.disburse.wizard'].with_user(self.finance_user).create({
            'advance_id': advance.id,
            'date': when or self.today,
        })
        if create_entry is not None:
            wizard.create_entry = create_entry
        wizard.action_disburse()
        return advance

    def _resign(self, employee, last_day, approve=False):
        resignation = self.env['employee.resignation'].create({
            'employee_id': employee.id,
            'last_working_day': last_day,
            'reason': 'personal',
            'resignation_body': '<p>Resigning</p>',
        })
        resignation.action_submit()
        if approve:
            resignation.action_approve()
        return resignation


class SalaryAdvanceCommon(SalaryAdvanceTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Tests render reports as HTML, which Sign cannot read: return a real PDF.
        cls.startClassPatcher(patch(
            f'{REPORT_MODEL}._render_qweb_pdf', lambda *args, **kwargs: (make_pdf('Undertaking'), 'pdf'),
        ))
        cls._setup_salary_advance_data()


def month_start(day, months=0):
    return (day + relativedelta(months=months)).replace(day=1)

