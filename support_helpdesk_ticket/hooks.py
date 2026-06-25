# -- coding: utf-8 --
##############################################################################
#                                                                            #
# Part of WebbyCrown Solutions (Website: www.webbycrown.com).                #
# Copyright © 2025 WebbyCrown Solutions. All Rights Reserved.                #
#                                                                            #
##############################################################################

import logging

_logger = logging.getLogger(__name__)


def _set_default_team_category_params(env):
    """Set helpdesk default team/category system parameters if missing (do not override user config)."""
    icp = env['ir.config_parameter'].sudo()
    team = env.ref(
        'support_helpdesk_ticket.dummy_helpdesk_team_default',
        raise_if_not_found=False,
    )
    category = env.ref(
        'support_helpdesk_ticket.dummy_helpdesk_category_general',
        raise_if_not_found=False,
    )
    if not team or not category:
        _logger.warning(
            'Dummy helpdesk team/category records are missing; skipping default config parameters.'
        )
        return
    if not icp.get_param('helpdesk.default_team_id'):
        icp.set_param('helpdesk.default_team_id', str(team.id))
    if not icp.get_param('helpdesk.default_category_id'):
        icp.set_param('helpdesk.default_category_id', str(category.id))


def post_init_hook(env):
    """Odoo 19+ passes a ready Environment; older versions used (cr, registry)."""
    _set_default_team_category_params(env)
