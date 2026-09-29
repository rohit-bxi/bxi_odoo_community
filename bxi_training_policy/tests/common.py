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


class TrainingTestMixin:
    """A department with its head, an employee reporting to a manager, HR, ES and Finance users,
    and the policy defaults."""

    @classmethod
    def _setup_training_data(cls):
        # The tests must not depend on the configuration of the database they run on.
        cls.company = cls.env.company
        cls.company.country_id = cls.env.ref('base.in')
        set_param = cls.env['ir.config_parameter'].sudo().set_param
        for key, value in {
            'lead_days': 20, 'form_days': 7, 'agreement_threshold': 30000, 'claim_days': 30,
            'claim_reminder_days': 7, 'stamp_paper_value': 100, 'agreement_reminder_days': 3,
            'expiry_notice_days': 30,
        }.items():
            set_param(f'bxi_training_policy.{key}', value)
        cls.company.write({
            'trn_hr_user_id': False, 'trn_es_user_id': False, 'trn_finance_user_id': False,
            'trn_policy_id': False, 'trn_accounting_mode': 'bonded',
            'trn_advance_account_id': False, 'trn_bonded_account_id': False, 'trn_expense_account_id': False,
            'trn_recovery_account_id': False, 'trn_journal_id': False, 'trn_misc_journal_id': False,
        })
        cls.env['bxi.training.agreement.tier'].search([('company_id', '!=', False)]).unlink()
        cls.today = fields.Date.today()

        cls.hr_user = new_test_user(
            cls.env, login='trn_test_hr', name='HR Officer',
            groups='base.group_user,bxi_training_policy.group_training_hr')
        cls.es_user = new_test_user(
            cls.env, login='trn_test_es', name='Employee Services',
            groups='base.group_user,bxi_training_policy.group_training_es')
        cls.finance_user = new_test_user(
            cls.env, login='trn_test_finance', name='Finance User',
            groups='base.group_user,bxi_training_policy.group_training_finance,hr_expense.group_hr_expense_manager')
        cls.head = cls._create_employee('Department Head')
        cls.department = cls.env['hr.department'].create({'name': 'Test Engineering', 'manager_id': cls.head.id})
        cls.manager = cls._create_employee('Team Manager', parent=cls.head, department=cls.department)
        cls.employee = cls._create_employee('Engineer', parent=cls.manager, department=cls.department)
        cls.fee_product = cls.env.ref('bxi_training_policy.product_training_fee')
        cls.lodging_product = cls.env.ref('bxi_training_policy.product_training_lodging')

    @classmethod
    def _create_employee(cls, name, parent=None, department=None):
        login = 'trn_test_' + name.lower().replace(' ', '_')
        user = new_test_user(cls.env, login=login, groups='base.group_user', email=f"{login}@example.com", name=name)
        return cls.env['hr.employee'].create({
            'name': name,
            'user_id': user.id,
            'parent_id': parent.id if parent else False,
            'department_id': department.id if department else False,
            'work_email': f"{login}@example.com",
        })

    @classmethod
    def _setup_accounting(cls):
        Account = cls.env['account.account']
        cls.advance_account = Account.create({
            'code': 'TR1301', 'name': 'Training Advances', 'account_type': 'asset_receivable', 'reconcile': True})
        cls.bonded_account = Account.create({
            'code': 'TR1401', 'name': 'Bonded Training Cost', 'account_type': 'asset_current'})
        cls.expense_account = Account.create({
            'code': 'TR6101', 'name': 'Training Expense', 'account_type': 'expense'})
        cls.salary_payable = Account.create({
            'code': 'TR2101', 'name': 'Salary Payable', 'account_type': 'liability_current', 'reconcile': True})
        cls.payable_account = Account.create({
            'code': 'TR2111', 'name': 'Employee Payable', 'account_type': 'liability_payable', 'reconcile': True})
        bank_account = Account.create({'code': 'TR1101', 'name': 'Training Bank', 'account_type': 'asset_cash'})
        for employee in (cls.employee, cls.manager):
            employee.work_contact_id.with_company(cls.company).property_account_payable_id = cls.payable_account
        cls.bank_journal = cls.env['account.journal'].create({
            'name': 'TRN Bank', 'type': 'bank', 'code': 'TRBK', 'default_account_id': bank_account.id})
        cls.misc_journal = cls.env['account.journal'].create({'name': 'TRN Misc', 'type': 'general', 'code': 'TRMS'})
        cls.company.write({
            'trn_advance_account_id': cls.advance_account.id,
            'trn_bonded_account_id': cls.bonded_account.id,
            'trn_expense_account_id': cls.expense_account.id,
            'trn_recovery_account_id': cls.salary_payable.id,
            'trn_journal_id': cls.bank_journal.id,
            'trn_misc_journal_id': cls.misc_journal.id,
        })

    # ── Workflow helpers ─────────────────────────────────────────────────
    def _new_training(self, fee=40000, lodging=20000, start_in=30, days=5, employee=None, **vals):
        """A nomination by the Department Head: the fee paid by the company, lodging by the employee."""
        start = self.today + relativedelta(days=start_in)
        values = {
            'employee_id': (employee or self.employee).id,
            'training_name': 'Advanced Kubernetes',
            'location': 'Bengaluru',
            'purpose': 'Cloud migration project',
            'start_date': start,
            'end_date': start + relativedelta(days=days - 1),
            'cost_line_ids': [
                (0, 0, {'category': 'fee', 'paid_by': 'company', 'estimated_amount': fee}),
                (0, 0, {'category': 'lodging', 'paid_by': 'employee', 'estimated_amount': lodging}),
            ],
        }
        values.update(vals)
        return self.env['bxi.training.request'].with_user(self.head.user_id).create(values)

    def _nominate(self, training):
        training.action_submit()
        training.with_user(self.hr_user).action_hr_confirm()
        return training.with_env(self.env)

    def _execute_agreement(self, training):
        """The employee uploads the notarised agreement and HR verifies it."""
        agreement = training.agreement_id
        scan = self.env['ir.attachment'].with_user(self.employee.user_id).create({
            'name': 'agreement.pdf', 'raw': make_pdf('Executed agreement')})
        agreement.with_user(self.employee.user_id).write({
            'stamp_paper_no': 'IN-KA123', 'stamp_paper_value': 100, 'stamp_paper_date': self.today,
            'witness1_name': 'Witness One', 'witness2_name': 'Witness Two',
            'notary_name': 'Notary Public', 'notarised_date': self.today,
            'executed_scan_ids': [(6, 0, scan.ids)],
        })
        agreement.with_user(self.employee.user_id).action_submit_execution()
        wizard = self.env['bxi.training.agreement.verify.wizard'].with_user(self.hr_user).create({
            'agreement_id': agreement.id,
            'check_stamp_paper': True, 'check_employee_signature': True, 'check_witnesses': True,
            'check_notary': True, 'check_terms': True,
        })
        wizard.action_verify()
        return agreement

    def _ready(self, training):
        """Nominated, form signed and, when required, agreement executed."""
        training = self._nominate(training)
        training._on_form_signed()
        if training.agreement_id:
            self._execute_agreement(training)
        return training

    def _pay_advance(self, training, amount=None, create_entry=None):
        wizard = self.env['bxi.training.advance.wizard'].with_user(self.finance_user).create({
            'request_id': training.id,
        })
        if amount is not None:
            wizard.amount = amount
        if create_entry is not None:
            wizard.create_entry = create_entry
        wizard.action_confirm()

    def _complete(self, training, end_date=None):
        """Start the training, let it happen (dates moved to the past) and record its completion."""
        training.with_user(self.hr_user).action_start()
        end = end_date or self.today
        training.sudo().write({'start_date': end - relativedelta(days=4), 'end_date': end})
        wizard = self.env['bxi.training.completion.wizard'].with_user(self.hr_user).create({
            'request_id': training.id,
        })
        wizard.end_date = end_date or self.today
        wizard.action_confirm()

    def _add_claim_line(self, training, product, amount):
        expense = self.env['hr.expense'].with_user(self.employee.user_id).create({
            'name': product.name,
            'product_id': product.id,
            'total_amount_currency': amount,
            'employee_id': self.employee.id,
            'training_request_id': training.id,
            'payment_mode': 'own_account',
        })
        self.env['ir.attachment'].create({
            'name': 'receipt.pdf', 'raw': make_pdf('Receipt'), 'res_model': 'hr.expense', 'res_id': expense.id})
        return expense

    def _approve_claim(self, training):
        training.with_user(self.manager.user_id).action_approve_claim()
        training.with_user(self.hr_user).action_approve_claim()
        training.with_user(self.es_user).action_approve_claim()

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


class TrainingCommon(TrainingTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Tests render reports as HTML, which Sign cannot read: return a real PDF.
        cls.startClassPatcher(patch(
            f'{REPORT_MODEL}._render_qweb_pdf', lambda *args, **kwargs: (make_pdf('Training document'), 'pdf'),
        ))
        cls._setup_training_data()
