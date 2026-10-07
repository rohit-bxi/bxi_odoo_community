from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Add the correction and TDS adjustment rules next to the existing deputation rules."""
    from odoo.addons.bxi_international_deputation import _deputation_rules
    env = api.Environment(cr, SUPERUSER_ID, {})
    rules = _deputation_rules(env)
    nopay = env.ref('bxi_international_deputation.hr_rule_deputation_nopay')
    env['hr.payroll.structure'].search([('rule_ids', 'in', nopay.id)]).write(
        {'rule_ids': [(4, rule.id) for rule in rules]})
