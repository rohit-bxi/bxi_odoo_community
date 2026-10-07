# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """LWPs created at missed check-out before this version are not flagged:
    flag them so they stay silent and show as LOP on the dashboard."""
    cr.execute("""
        UPDATE hr_leave
           SET is_missed_checkout_lwp = TRUE
         WHERE id IN (
                SELECT lwp_leave_id
                  FROM hr_attendance
                 WHERE lwp_leave_id IS NOT NULL
         )
    """)

    # Replaced by mail_template_missed_checkout_regularization, which is not
    # sent to the manager. Only databases installed before this version have it.
    env = api.Environment(cr, SUPERUSER_ID, {})
    old_template = env.ref(
        'bxi_attendance_missed_checkout.mail_template_missed_checkout_lwp',
        raise_if_not_found=False,
    )
    if old_template:
        old_template.unlink()
