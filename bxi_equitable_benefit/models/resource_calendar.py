from odoo import fields, models


class ResourceCalendar(models.Model):
    _inherit = 'resource.calendar'

    eb_is_odd_shift = fields.Boolean(
        string='Odd Shift (Equitable Benefit)',
        help="An odd hour, day or week shift (e.g. a night shift). Employees on an odd shift work pattern are "
             "checked to have worked on such a schedule.")
