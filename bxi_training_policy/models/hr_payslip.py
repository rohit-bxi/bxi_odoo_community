from odoo import _, models

TRAIN_REC_CODE = 'TRAIN_REC'


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def compute_sheet(self):
        self._sync_training_recovery_input()
        res = super().compute_sheet()
        capped = self._cap_training_recovery_to_net_pay()
        if capped:
            super(HrPayslip, capped).compute_sheet()
        return res

    def action_payslip_done(self):
        res = super().action_payslip_done()
        self._register_training_recovery()
        return res

    def action_payslip_cancel(self):
        self._revert_training_recovery()
        return super().action_payslip_cancel()

    def action_payslip_draft(self):
        self._revert_training_recovery()
        return super().action_payslip_draft()

    def _get_training_recovery_input(self):
        self.ensure_one()
        return self.input_line_ids.filtered(lambda line: line.code == TRAIN_REC_CODE)

    def _get_training_recoveries(self):
        self.ensure_one()
        return self.env['bxi.training.recovery'].sudo().search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'payroll'),
            ('payroll_month', '<=', self.date_to),
            ('balance', '>', 0),
        ])

    def _sync_training_recovery_input(self):
        """Put the training costs to recover up to the end of the payslip period on the TRAIN_REC input."""
        for slip in self.filtered(lambda s: s.state == 'draft' and not s.credit_note):
            amount = sum(slip._get_training_recoveries().mapped('balance'))
            line = slip._get_training_recovery_input()
            if line:
                line[:1].amount = amount
                (line - line[:1]).unlink()
            elif amount:
                slip.input_line_ids = [(0, 0, {
                    'name': _('Training Cost Recovery'),
                    'code': TRAIN_REC_CODE,
                    'amount': amount,
                    'sequence': 61,
                    'version_id': slip.version_id.id,
                })]

    def _cap_training_recovery_to_net_pay(self):
        """Never let the recovery make the net pay negative; return the payslips to recompute."""
        capped = self.browse()
        for slip in self.filtered(lambda s: s.state != 'done' and not s.credit_note):
            line = slip._get_training_recovery_input()[:1]
            currency = slip.currency_id
            if not line or currency.compare_amounts(line.amount, 0) <= 0:
                continue
            if currency.compare_amounts(slip.net_wage, 0) < 0:
                line.amount = currency.round(max(line.amount + slip.net_wage, 0.0))
                capped |= slip
        return capped

    def _register_training_recovery(self):
        for slip in self.filtered(lambda s: s.state == 'done' and not s.credit_note):
            recoveries = slip._get_training_recoveries()
            if not recoveries:
                continue
            recovered = abs(sum(slip.line_ids.filtered(lambda line: line.code == TRAIN_REC_CODE).mapped('total')))
            recoveries._register_payroll_recovery(slip, recovered)

    def _revert_training_recovery(self):
        slips = self.filtered(lambda s: s.state == 'done')
        if slips:
            self.env['bxi.training.recovery'].sudo()._revert_payroll_recovery(slips)
