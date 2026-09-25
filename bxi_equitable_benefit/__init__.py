from . import models
from . import wizard


def _post_init_hook(env):
    """Add the Equitable Benefit rule to every existing salary structure."""
    rule = env.ref('bxi_equitable_benefit.hr_rule_equitable_benefit')
    env['hr.payroll.structure'].search([]).write({'rule_ids': [(4, rule.id)]})
