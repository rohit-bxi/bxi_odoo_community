from . import controllers
from . import models
from . import wizard


def _post_init_hook(env):
    """Add the Equitable Benefit rules to every existing salary structure."""
    rules = env.ref('bxi_equitable_benefit.hr_rule_equitable_benefit') \
        | env.ref('bxi_equitable_benefit.hr_rule_equitable_benefit_tds')
    env['hr.payroll.structure'].search([]).write({'rule_ids': [(4, rule.id) for rule in rules]})
    env['hr.leave.type']._eb_flag_default_unpaid_types()
