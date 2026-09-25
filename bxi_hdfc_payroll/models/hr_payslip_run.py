# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    def action_hdfc_release(self):
        slips = self.slip_ids.filtered(lambda s: s.state == 'done')
        if not slips:
            raise UserError(_('There are no done payslips in this batch.'))
        return slips.action_hdfc_release()
