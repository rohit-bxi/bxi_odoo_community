import base64
import io
from datetime import timedelta

from reportlab.pdfgen import canvas

from odoo import fields
from odoo.tests import TransactionCase, new_test_user


def make_pdf(text='Policy'):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(100, 750, text)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


class PolicyTestMixin:
    """Two companies, an HR manager, a CPO, a manager and two employees."""

    @classmethod
    def _setup_policy_data(cls):
        cls.today = fields.Date.today()
        cls.company = cls.env.company
        cls.other_company = cls.env['res.company'].create({'name': 'Policy Test Other Co'})
        cls.hr_manager = new_test_user(cls.env, login='policy_test_hr', groups='base.group_user,hr.group_hr_manager',
                                       email='policy_test_hr@example.com',
                                       company_ids=[(6, 0, (cls.company | cls.other_company).ids)])
        cls.cpo = new_test_user(cls.env, login='policy_test_cpo', groups='base.group_user,bxi_hr_policy.group_policy_cpo',
                                email='policy_test_cpo@example.com')
        cls.manager = cls._employee('Policy Manager')
        cls.employee = cls._employee('Policy Employee', parent=cls.manager)
        cls.other_employee = cls._employee('Policy Other', company=cls.other_company)
        cls.no_user_employee = cls.env['hr.employee'].create({'name': 'Policy No User'})
        cls.policy = cls.env['hr.company.policy'].create({
            'name': 'Test Antitrust Policy',
            'company_id': False,
            'scope': 'all',
            'ack_due_days': 7,
            'reminder_interval_days': 2,
            'escalate_manager_after_days': 3,
            'escalate_hr_after_days': 7,
        })

    @classmethod
    def _employee(cls, name, parent=None, company=None):
        login = 'policy_test_' + name.lower().replace(' ', '_')
        company = company or cls.env.company
        user = new_test_user(cls.env, login=login, groups='base.group_user', email=f'{login}@example.com',
                             company_id=company.id, company_ids=[(6, 0, company.ids)])
        return cls.env['hr.employee'].create({
            'name': name, 'user_id': user.id, 'company_id': company.id,
            'parent_id': parent.id if parent else False,
        })

    def _version(self, policy=None, **vals):
        values = {
            'policy_id': (policy or self.policy).id,
            'document': base64.b64encode(make_pdf()),
            'filename': 'policy.pdf',
            'valid_from': self.today,
        }
        values.update(vals)
        return self.env['hr.company.policy.version'].with_user(self.hr_manager).create(values)

    def _publish(self, version=None, policy=None):
        version = version or self._version(policy)
        version.with_user(self.hr_manager).action_submit()
        version.with_user(self.cpo).action_approve()
        version.with_user(self.hr_manager).action_publish()
        return version

    def _acks(self, version):
        return self.env['hr.policy.acknowledgement'].search([('version_id', '=', version.id)])

    def _ack_of(self, version, employee):
        return self._acks(version).filtered(lambda a: a.employee_id == employee)

    def _shift_dates(self, acks, days):
        """Pretend the acknowledgements were requested ``days`` ago."""
        for ack in acks:
            ack.sudo().write({
                'requested_date': ack.requested_date - timedelta(days=days),
                'due_date': ack.due_date - timedelta(days=days),
            })


class PolicyCommon(PolicyTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_policy_data()
