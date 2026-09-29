from . import controllers
from . import models
from . import wizard


def _post_init_hook(env):
    """Add the training cost recovery rule to every existing salary structure."""
    rule = env.ref('bxi_training_policy.hr_rule_training_recovery')
    env['hr.payroll.structure'].search([]).write({'rule_ids': [(4, rule.id)]})
