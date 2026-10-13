# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """The weekly reminder to each employee is replaced by the manager and
    HR summaries."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    old_template = env.ref(
        'bxi_shift_management.mail_template_attendance_regularization_reminder',
        raise_if_not_found=False,
    )
    if old_template:
        old_template.unlink()
