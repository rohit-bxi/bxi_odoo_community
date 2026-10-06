from odoo import SUPERUSER_ID, api

# The policy parameters are noupdate data: apply the revised policy to existing databases.
POLICY_VALUES = {
    'bxi_salary_advance.limit_percent': '50',
    'bxi_salary_advance.min_service_months': '12',
}
# Replaced by the single limit, the 3 standard EMIs and the service rule for every category.
OBSOLETE_KEYS = [
    'bxi_salary_advance.emergency_installments',
    'bxi_salary_advance.housing_tenancies',
    'bxi_salary_advance.housing_limit_percent',
    'bxi_salary_advance.nonprocessing_require_service',
]
OBSOLETE_XMLIDS = ['param_emergency_installments', 'param_housing_tenancies']


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Param = env['ir.config_parameter']
    for key, value in POLICY_VALUES.items():
        Param.set_param(key, value)
    Param.search([('key', 'in', OBSOLETE_KEYS)]).unlink()
    env['ir.model.data'].search([
        ('module', '=', 'bxi_salary_advance'), ('name', 'in', OBSOLETE_XMLIDS),
    ]).unlink()

    # Requests HR has not processed yet follow the 3 standard EMIs; approved ones keep their terms.
    env['bxi.salary.advance'].search([
        ('state', 'in', ('draft', 'submitted', 'hr_review')),
    ]).write({'installment_count': 3})
