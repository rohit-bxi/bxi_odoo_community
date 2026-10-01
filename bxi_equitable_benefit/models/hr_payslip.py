from odoo import _, models

EQB_CODE = 'EQB'


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def compute_sheet(self):
        self._sync_equitable_benefit_input()
        return super().compute_sheet()

    def action_payslip_done(self):
        res = super().action_payslip_done()
        payouts = self.env['bxi.eb.payout'].sudo().search([
            ('payslip_id', 'in', self.filtered(lambda s: s.state == 'done').ids),
            ('state', '=', 'approved'),
        ])
        payouts.write({'state': 'paid'})
        for payout in payouts:
            payout._eb_notify_employee(_(
                "Your Equitable Benefit of %(amount)s for %(fy)s was paid with payslip %(slip)s.",
                amount=payout.currency_id.format(payout.amount_final), fy=payout.fy_name,
                slip=payout.payslip_id.number or payout.payslip_id.name))
        return res

    def action_payslip_cancel(self):
        self.env['bxi.eb.payout'].sudo().search([
            ('payslip_id', 'in', self.ids), ('state', 'in', ('approved', 'paid')),
        ]).write({'payslip_id': False, 'state': 'approved'})
        return super().action_payslip_cancel()

    def _sync_equitable_benefit_input(self):
        """Put approved Equitable Benefit payouts due in the payslip period on the EQB input."""
        Payout = self.env['bxi.eb.payout'].sudo()
        for slip in self.filtered(lambda s: s.state == 'draft' and not s.credit_note):
            payouts = Payout.search([
                ('employee_id', '=', slip.employee_id.id),
                ('state', '=', 'approved'),
                ('payout_date', '>=', slip.date_from),
                ('payout_date', '<=', slip.date_to),
                '|', ('payslip_id', '=', False), ('payslip_id', '=', slip.id),
            ])
            Payout.search([('payslip_id', '=', slip.id), ('id', 'not in', payouts.ids)]).payslip_id = False
            payouts.payslip_id = slip
            amount = sum(payouts.mapped('amount_final'))
            line = slip.input_line_ids.filtered(lambda l: l.code == EQB_CODE)
            if line:
                line[:1].amount = amount
                (line - line[:1]).unlink()
            elif amount:
                slip.input_line_ids = [(0, 0, {
                    'name': _('Equitable Benefit'),
                    'code': EQB_CODE,
                    'amount': amount,
                    'sequence': 50,
                    'version_id': slip.version_id.id,
                })]
