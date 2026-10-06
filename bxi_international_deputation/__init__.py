from . import models
from . import wizard


def _post_init_hook(env):
    """Add the deputation proration rules to every existing salary structure."""
    env['hr.payroll.structure'].search([]).write({'rule_ids': [(4, rule.id) for rule in _deputation_rules(env)]})


def _deputation_rules(env):
    return env['hr.salary.rule'].browse([env.ref('bxi_international_deputation.%s' % xmlid).id for xmlid in (
        'hr_rule_deputation_nopay',
        'hr_rule_deputation_pf_adjustment',
        'hr_rule_deputation_retro',
        'hr_rule_deputation_retro_pf',
        'hr_rule_deputation_tds_adjustment',
    )])
