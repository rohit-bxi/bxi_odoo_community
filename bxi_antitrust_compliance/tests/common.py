from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, new_test_user


class ComplianceTestMixin:

    @classmethod
    def _setup_compliance_data(cls):
        cls.today = fields.Date.today()
        cls.env['ir.config_parameter'].sudo().set_param('bxi_antitrust_compliance.contact_email',
                                                        'compliance.test@example.com')
        cls.env.company.bid_cpo_signoff = False
        cls.cpo = new_test_user(cls.env, login='cmp_test_cpo', groups='base.group_user,bxi_hr_policy.group_policy_cpo',
                                email='cmp_test_cpo@example.com')
        cls.manager = cls._employee('Cmp Manager')
        cls.employee = cls._employee('Cmp Employee', parent=cls.manager)
        cls.colleague = cls._employee('Cmp Colleague')
        cls.salesman = new_test_user(cls.env, login='cmp_test_sales', email='cmp_test_sales@example.com',
                                     groups='base.group_user,sales_team.group_sale_salesman_all_leads')

    @classmethod
    def _employee(cls, name, parent=None):
        login = 'cmp_test_' + name.lower().replace(' ', '_')
        user = new_test_user(cls.env, login=login, groups='base.group_user', email=f'{login}@example.com')
        return cls.env['hr.employee'].create({
            'name': name, 'user_id': user.id, 'parent_id': parent.id if parent else False,
        })

    def _cpo_activities(self, record):
        return record.sudo().activity_ids.filtered(lambda a: a.user_id == self.cpo)

    def _contact_messages(self, record):
        contact = self.env['antitrust.mixin']._contact_partner()
        return record.sudo().message_ids.filtered(lambda m: contact in m.partner_ids)

    def _interaction(self, user=None, **vals):
        values = {
            'employee_id': self.employee.id,
            'interaction_type': 'industry_event',
            'event_date': self.today + timedelta(days=5),
            'organisations': 'Competitor Ltd',
            'purpose': 'Industry panel',
            'commit_no_topics': True,
            'commit_report': True,
        }
        values.update(vals)
        return self.env['antitrust.interaction'].with_user(user or self.employee.user_id).create(values)


class ComplianceCommon(ComplianceTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_compliance_data()
