# -*- coding: utf-8 -*-

from odoo import models, fields


class RequestTypeTeam(models.Model):
    _name = 'request.type.team'
    _description = 'Request Type Team'

    name = fields.Char(
        string='Team Name',
        required=True,
    )
    email = fields.Char(
        string='Email',
        required=True,
    )
    is_manager = fields.Boolean(
        string='Manager Team',
        default=False,
    )
    is_team = fields.Boolean(
        string="Team Level Access",
        default=False,
        help="If enabled, members of this team can view all onboarding and offboarding requests."
    )

    user_ids = fields.Many2many(
        'res.users',
        'request_type_team_user_rel',
        'team_id',
        'user_id',
        string="Team Members"
    )

