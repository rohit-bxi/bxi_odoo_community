from odoo import _, models

from .salary_advance import RECOVERY_STATES

SAL_ADV_CODE = 'SAL_ADV'


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def compute_sheet(self):
        self._sync_salary_advance_input()
        res = super().compute_sheet()
        capped = self._cap_salary_advance_to_net_pay()
        if capped:
            super(HrPayslip, capped).compute_sheet()
        return res

    def action_payslip_done(self):
        res = super().action_payslip_done()
        self._register_salary_advance_recovery()
        return res

    def action_payslip_cancel(self):
        self._revert_salary_advance_recovery()
        return super().action_payslip_cancel()

    def action_payslip_draft(self):
        self._revert_salary_advance_recovery()
        return super().action_payslip_draft()

    def _get_salary_advance_input(self):
        self.ensure_one()
        return self.input_line_ids.filtered(lambda line: line.code == SAL_ADV_CODE)

    def _sync_salary_advance_input(self):
        """Put the salary advance EMIs due up to the end of the payslip period on the SAL_ADV input.

        EMIs of earlier months that were not deducted yet are included as well."""
        Installment = self.env['bxi.salary.advance.installment'].sudo()
        for slip in self.filtered(lambda s: s.state == 'draft' and not s.credit_note):
            installments = Installment.search([
                ('employee_id', '=', slip.employee_id.id),
                ('state', '=', 'pending'),
                ('advance_id.state', 'in', RECOVERY_STATES),
                ('due_date', '<=', slip.date_to),
                '|', '|',
                ('payslip_id', '=', False),
                ('payslip_id', '=', slip.id),
                ('payslip_id.state', '=', 'cancel'),
            ])
            Installment.search([
                ('payslip_id', '=', slip.id), ('state', '=', 'pending'), ('id', 'not in', installments.ids),
            ]).payslip_id = False
            installments.payslip_id = slip
            amount = sum(installments.mapped('amount'))
            line = slip._get_salary_advance_input()
            if line:
                line[:1].amount = amount
                (line - line[:1]).unlink()
            elif amount:
                slip.input_line_ids = [(0, 0, {
                    'name': _('Salary Advance Recovery'),
                    'code': SAL_ADV_CODE,
                    'amount': amount,
                    'sequence': 60,
                    'version_id': slip.version_id.id,
                })]

    def _cap_salary_advance_to_net_pay(self):
        """Never let the recovery make the net pay negative; return the payslips to recompute."""
        capped = self.browse()
        for slip in self.filtered(lambda s: s.state != 'done' and not s.credit_note):
            line = slip._get_salary_advance_input()[:1]
            currency = slip.currency_id
            if not line or currency.compare_amounts(line.amount, 0) <= 0:
                continue
            if currency.compare_amounts(slip.net_wage, 0) < 0:
                line.amount = currency.round(max(line.amount + slip.net_wage, 0.0))
                capped |= slip
        return capped

    def _register_salary_advance_recovery(self):
        Installment = self.env['bxi.salary.advance.installment'].sudo()
        for slip in self.filtered(lambda s: s.state == 'done' and not s.credit_note):
            installments = Installment.search([('payslip_id', '=', slip.id), ('state', '=', 'pending')])
            if not installments:
                continue
            recovered = abs(sum(slip.line_ids.filtered(lambda line: line.code == SAL_ADV_CODE).mapped('total')))
            installments._register_recovery(slip, recovered)
            for advance in installments.advance_id:
                deducted = advance.installment_ids.filtered(
                    lambda inst: inst.payslip_id == slip and inst.state == 'deducted' and not inst.move_id)
                advance._post_recovery_move(slip, deducted)
            installments.advance_id._check_closed()

    def _revert_salary_advance_recovery(self):
        Installment = self.env['bxi.salary.advance.installment'].sudo()
        slips = self.filtered(lambda s: s.state == 'done')
        if not slips:
            return
        installments = Installment.search([('payslip_id', 'in', slips.ids), ('state', '=', 'deducted')])
        installments._revert_recovery()
        installments.advance_id._reopen()
