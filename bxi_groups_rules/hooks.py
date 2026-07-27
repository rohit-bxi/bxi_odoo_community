# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """
    After installation, link the 'Base Employee' group to the same privilege_id
    as hr.group_hr_user so it appears in the Employees dropdown on the User form
    (visible without debug mode alongside Officer & Administrator).
    """
    try:
        group_base = env.ref('bxi_groups_rules.group_hr_employee_base', raise_if_not_found=False)
        group_officer = env.ref('hr.group_hr_user', raise_if_not_found=False)

        if group_base and group_officer and group_officer.privilege_id:
            group_base.sudo().write({
                'privilege_id': group_officer.privilege_id.id,
                'sequence': 1,
            })
            _logger.info(
                "bxi_groups_rules: Base Employee group linked to privilege '%s'",
                group_officer.privilege_id.name,
            )
        else:
            _logger.warning(
                "bxi_groups_rules: Could not link Base Employee group — "
                "group_base=%s, group_officer=%s, privilege=%s",
                group_base, group_officer,
                group_officer.privilege_id if group_officer else None,
            )
    except Exception as exc:
        _logger.error("bxi_groups_rules post_init_hook failed: %s", exc)
