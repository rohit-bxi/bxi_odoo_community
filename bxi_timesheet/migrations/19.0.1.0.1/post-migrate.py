# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Shift wise production hours are never more than the ACS (productive) hours."""
    cr.execute("""
        UPDATE bxi_desktime_log
           SET shift_productive_hours = COALESCE(productive_hours, 0.0)
         WHERE shift_productive_hours > COALESCE(productive_hours, 0.0)
    """)
