# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Exception requests were created with a wrong sequence code and are
    all named "/". Number them in creation order."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    requests = env['bxi.shift.exception'].search([('name', '=', '/')], order='id')
    for request in requests:
        request.name = env['ir.sequence'].next_by_code('bxi.exception.request')
