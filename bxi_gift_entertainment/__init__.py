from . import models
from . import wizard


def _post_init_hook(env):
    """The matrix is in INR (India) and USD (other countries): both currencies must be active."""
    env['res.currency'].with_context(active_test=False).search([('name', 'in', ('USD', 'INR'))]).active = True
