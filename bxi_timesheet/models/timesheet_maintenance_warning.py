# -*- coding: utf-8 -*-
from odoo import models, fields

class TimesheetMaintenanceWarning(models.TransientModel):
    _name = 'timesheet.maintenance.warning'
    _description = 'Timesheet Maintenance Notice'

    name = fields.Char(
        string="Notice",
        default="Due to maintenance, the module is currently not working. We will inform once the maintenance is completed.",
        readonly=True
    )
