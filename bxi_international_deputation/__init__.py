from . import models
from . import wizard


def _post_init_hook(env):
    """Add the deputation proration rules to every existing salary structure."""
    rules = env.ref('bxi_international_deputation.hr_rule_deputation_nopay') \
        | env.ref('bxi_international_deputation.hr_rule_deputation_pf_adjustment')
    env['hr.payroll.structure'].search([]).write({'rule_ids': [(4, rule.id) for rule in rules]})
