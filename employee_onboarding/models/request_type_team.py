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
