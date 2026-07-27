# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    is_auto_checkout = fields.Boolean(string='Auto Check-out', default=False)
