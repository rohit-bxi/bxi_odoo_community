# -*- coding: utf-8 -*-
from odoo import fields, models


class HrLeaveType(models.Model):
    """Inherit hr_leave_type for adding code."""
    _inherit = "hr.leave.type"

    code = fields.Char(string="Code", help="Code for Time Off Type")
