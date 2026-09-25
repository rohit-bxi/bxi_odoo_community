from . import controllers
from . import models
from . import wizard


def _post_init_hook(env):
    """Add the salary advance recovery rule to every existing salary structure."""
    rule = env.ref('bxi_salary_advance.hr_rule_salary_advance')
    env['hr.payroll.structure'].search([]).write({'rule_ids': [(4, rule.id)]})
