# -*- coding: utf-8 -*-
from odoo import fields, models


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    is_missed_checkout_lwp = fields.Boolean(
        string='Missed Attendance LWP', readonly=True, copy=False, index=True,
        help='LWP applied automatically for a day without attendance regularization. '
             'No notification is sent to the manager or HR for it.')

    def _check_and_send_leave_notification(self):
        # bxi_leave_management mails the manager and HR on submission.
        return super(HrLeave, self.filtered(
            lambda leave: not leave.is_missed_checkout_lwp
        ))._check_and_send_leave_notification()
