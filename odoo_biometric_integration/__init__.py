from . import models
from . import wizard
from . import controller


def post_init_hook(env):
    env['hr.work.location']._essl_flag_default_biometric_locations()
