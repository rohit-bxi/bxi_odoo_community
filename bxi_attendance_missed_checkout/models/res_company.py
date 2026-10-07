# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    missed_checkout_lwp = fields.Boolean(
        string='Mark LWP on Missed Check-out',
        default=True,
        help='If an employee does not check out on an office or home day and does not '
             'regularize the attendance before the 25th, a full-day LWP is applied for that day.',
    )
    missed_checkout_lwp_start_date = fields.Date(
        string='Apply LWP From',
        default=fields.Date.context_today,
        help='Attendances checked in before this date are only closed, no LWP is created.',
    )
    attendance_regularization_start_date = fields.Date(
        string='Attendance Regularization From',
        default=lambda self: self._default_attendance_regularization_start_date(),
        help='Days without attendance before this date are not reminded, '
             'not marked LOP and keep their shift wise production hours.',
    )

    def _default_attendance_regularization_start_date(self):
        """Start of the open attendance cycle, so the whole cycle is covered."""
        Attendance = self.env['hr.attendance']
        return Attendance._get_regularization_cycle(Attendance._get_regularization_today())[0]
