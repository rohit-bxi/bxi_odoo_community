from odoo.tests import HttpCase, tagged

from .common import ComplianceTestMixin


@tagged('post_install', '-at_install')
class TestComplianceDashboardUi(ComplianceTestMixin, HttpCase):
    browser_size = '1440x1500'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_compliance_data()
        cls.cpo.password = 'cmp_test_cpo'

    def test_dashboard_renders_and_opens_lists(self):
        query = self.env['antitrust.query'].with_user(self.employee.user_id).create(
            {'subject': 'Can we share our price list with a partner?', 'situation': '<p>?</p>', 'urgency': 'urgent'})
        query.action_submit()
        self._interaction(interaction_type='joint_bid').action_submit()
        self.env['antitrust.case'].with_user(self.cpo).create({
            'employee_ids': [(6, 0, self.employee.ids)], 'summary': 'Price discussion at a trade association',
            'follow_up_date': self.today.replace(day=1).replace(year=self.today.year - 1)})

        url = '/odoo/action-bxi_antitrust_compliance.action_compliance_dashboard'
        ready = "document.querySelectorAll('.o_compliance_dashboard .o_cd_kpi').length === 6"

        self.browser_js(url, "console.log('test successful')", ready=ready, login='cmp_test_cpo')

        # A KPI card opens the matching list, a worklist row opens the record
        click_card = """
            document.querySelectorAll('.o_compliance_dashboard .o_cd_kpi')[1].click();
            const wait = setInterval(() => {
                if (document.querySelector('.o_list_view .o_data_row')) {
                    clearInterval(wait);
                    console.log('test successful');
                }
            }, 100);
        """
        self.browser_js(url, click_card, ready=ready, login='cmp_test_cpo')
        click_row = """
            document.querySelector('.o_compliance_dashboard .o_cd_table tbody tr').click();
            const wait = setInterval(() => {
                if (document.querySelector('.o_form_view')) {
                    clearInterval(wait);
                    console.log('test successful');
                }
            }, 100);
        """
        self.browser_js(url, click_row, ready=ready, login='cmp_test_cpo')
