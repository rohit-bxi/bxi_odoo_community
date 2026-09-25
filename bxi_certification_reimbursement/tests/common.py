import io
from datetime import timedelta
from unittest.mock import patch

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


class CertificationTestMixin:
    """Shared data: an India company, a banded reporting line and an approved list.

    A higher band is more senior; the CEO at the top has no band:
        CEO -> Band Four (4.1) -> Band Three (3.2) -> Band Two (2.1) -> Lead (1.2) -> Engineer (1.1)
    """

    @classmethod
    def _setup_certification_data(cls):
        # The tests must not depend on the data of the database they run on
        # (configured parameters, tiers, existing codes and users).
        cls.env.company.country_id = cls.env.ref('base.in')
        set_param = cls.env['ir.config_parameter'].sudo().set_param
        set_param('bxi_certification_reimbursement.claim_days_limit', 90)
        set_param('bxi_certification_reimbursement.band4_limit', 5000)
        set_param('bxi_certification_reimbursement.voucher_reminder_days', 7)
        set_param('bxi_certification_reimbursement.inclusion_sla_days', 10)
        Tier = cls.env['bxi.service.agreement.tier']
        Tier.search([]).unlink()
        cls.tier_6 = Tier.create({'min_amount': 8000, 'max_amount': 19999.99, 'months': 6})
        Tier.create({'min_amount': 20000, 'max_amount': 50000, 'months': 12})
        Tier.create({'min_amount': 50000.01, 'max_amount': 0, 'months': 18})
        # Reuse an existing plan: creating one adds a column and reloads the registry.
        cls.plan = cls.env['account.analytic.plan'].search([], limit=1) \
            or cls.env['account.analytic.plan'].create({'name': 'Cost Centres'})
        cls.cost_center = cls.env['account.analytic.account'].create({
            'name': 'CC Band 4', 'plan_id': cls.plan.id,
        })

        cls.ceo = cls._create_employee('CEO', False)
        cls.band4 = cls._create_employee('Band Four', '4.1', cls.ceo, cost_center_id=cls.cost_center.id)
        cls.band3 = cls._create_employee('Band Three', '3.2', cls.band4)
        cls.band2 = cls._create_employee('Band Two', '2.1', cls.band3)
        cls.manager = cls._create_employee('Lead', '1.2', cls.band2)
        cls.engineer = cls._create_employee('Engineer', '1.1', cls.manager)
        cls.academy_head = cls._create_employee('Academy Head', '3.1', cls.band4)
        cls.academy_head.user_id.group_ids |= cls.env.ref(
            'bxi_certification_reimbursement.group_certification_academy')

        cls.lob = cls.env['bxi.line.of.business'].create({
            'name': 'Test Digital', 'code': 'TEST-DB', 'academy_head_id': cls.academy_head.id,
            'academy_user_ids': [(6, 0, cls.academy_head.user_id.ids)],
        })
        cls.engineer.lob_id = cls.lob

        cls.certification = cls.env['bxi.certification'].create({
            'name': 'Test Cloud Architect', 'certifying_body': 'Cloud Inc', 'website': 'https://example.com',
            'cost': 4000, 'lob_id': cls.lob.id, 'code': 'TEST-CLOUD',
        })
        cls.udemy = cls.env['bxi.certification'].create({
            'name': 'Test Python Course', 'certifying_body': 'Udemy', 'website': 'https://udemy.com',
            'is_udemy': True, 'lob_id': cls.lob.id,
        })
        cls.exam_fee = cls.env.ref('bxi_certification_reimbursement.product_certification_exam_fee')
        cls.dd_charges = cls.env.ref('bxi_certification_reimbursement.product_certification_dd_charges')
        cls.courier = cls.env.ref('bxi_certification_reimbursement.product_certification_courier')
        cls.meals = cls.env.ref('hr_expense.expense_product_meal')
        cls.pdf = cls.env['ir.attachment'].create({'name': 'certificate.pdf', 'raw': make_pdf('Certificate')})
        cls.today = fields.Date.today()

    @classmethod
    def _create_employee(cls, name, band, parent=None, **extra):
        login = 'cert_test_' + name.lower().replace(' ', '_')
        user = new_test_user(cls.env, login=login, groups='base.group_user',
                             email=f"{login}@example.com", name=name)
        return cls.env['hr.employee'].create(dict({
            'name': name,
            'role_band': band,
            'user_id': user.id,
            'parent_id': parent.id if parent else False,
            'work_email': f"{login}@example.com",
        }, **extra))

    # ── Workflow helpers ─────────────────────────────────────────────────
    def _new_request(self, certification=None, employee=None, **vals):
        values = {
            'employee_id': (employee or self.engineer).id,
            'cost_centre_ack': True,
        }
        if certification is None:
            values['certification_id'] = self.certification.id
        elif certification:
            values['certification_id'] = certification.id
        else:
            values.update(certification_name='Unlisted Cert', certifying_body='Someone')
        values.update(vals)
        return self.env['bxi.certification.request'].create(values)

    def _pre_approve(self, request):
        request.action_submit()
        request.with_user(request.manager_id.user_id).action_rm_approve()
        return request

    def _add_lines(self, request, amounts, products=None):
        products = products or [self.exam_fee, self.courier, self.dd_charges]
        return self.env['hr.expense'].create([{
            'name': f'Line {index}',
            'product_id': products[index % len(products)].id,
            'employee_id': request.employee_id.id,
            'total_amount_currency': amount,
            'certification_request_id': request.id,
        } for index, amount in enumerate(amounts)])

    def _prepare_claim(self, request, amounts, days_ago=10):
        request.write({
            'exam_clear_date': self.today - timedelta(days=days_ago),
            'attempt_passed': True,
            'certificate_attachment_ids': [(6, 0, self.pdf.ids)],
        })
        self._add_lines(request, amounts)
        return request

    def _claim(self, request, amounts, days_ago=10):
        self._prepare_claim(request, amounts, days_ago)
        request.action_submit_claim()
        return request

    def _approve_all(self, request):
        while request.current_approver_id:
            request.with_user(request.current_approver_id.user_id).action_approve_claim()
        return request

    def _full_claim(self, amounts, days_ago=10, certification=None, employee=None):
        request = self._pre_approve(self._new_request(certification, employee=employee))
        return self._approve_all(self._claim(request, amounts, days_ago))

    def _resign(self, employee, submit=True):
        resignation = self.env['employee.resignation'].create({
            'employee_id': employee.id,
            'last_working_day': self.today + timedelta(days=30),
            'reason': 'personal',
            'resignation_body': '<p>Resigning</p>',
        })
        if submit:
            resignation.action_submit()
        return resignation

    def _create_agreement(self, **vals):
        values = {
            'employee_id': self.engineer.id,
            'amount': 9000,
            'period_months': 6,
            'start_date': self.today - timedelta(days=30),
        }
        values.update(vals)
        return self.env['bxi.service.agreement'].create(values)


class CertificationCommon(CertificationTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Tests render reports as HTML, which Sign cannot read: return a real PDF.
        cls.startClassPatcher(patch(
            f'{REPORT_MODEL}._render_qweb_pdf', lambda *args, **kwargs: (make_pdf('Agreement'), 'pdf'),
        ))
        cls._setup_certification_data()
