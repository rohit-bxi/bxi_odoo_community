from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Add the TDS rule next to the Equitable Benefit rule and flag the unpaid leave types."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    rule = env.ref('bxi_equitable_benefit.hr_rule_equitable_benefit')
    tds_rule = env.ref('bxi_equitable_benefit.hr_rule_equitable_benefit_tds')
    env['hr.payroll.structure'].search([('rule_ids', 'in', rule.id)]).write({'rule_ids': [(4, tds_rule.id)]})
    env['hr.leave.type']._eb_flag_default_unpaid_types()
