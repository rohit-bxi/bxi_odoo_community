# -- coding: utf-8 --
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
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
        return
    if not icp.get_param('helpdesk.default_team_id'):
        icp.set_param('helpdesk.default_team_id', str(team.id))
    if not icp.get_param('helpdesk.default_category_id'):
        icp.set_param('helpdesk.default_category_id', str(category.id))
