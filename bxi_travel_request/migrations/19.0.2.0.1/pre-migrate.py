# Remap selection keys renamed/removed in 19.0.2.0.0 so existing records
# render (the web client crashes on a stored value missing from the selection).

STATE_MAP = {
    'approve': 'approved',
    'cancel': 'cancelled',
    # Finance step no longer exists; send back to the last internal approver.
    'finance_approval': 'hr_approval',
}

MODE_MAP = {
    'car': 'cab',
}


def _remap(cr, column, mapping):
    for old, new in mapping.items():
        cr.execute(
            f"UPDATE travel_request SET {column} = %s WHERE {column} = %s",
            (new, old),
        )


def migrate(cr, version):
    _remap(cr, 'state', STATE_MAP)
    _remap(cr, 'mode_of_travel', MODE_MAP)
