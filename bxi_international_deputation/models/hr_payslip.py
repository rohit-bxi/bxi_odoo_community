from odoo import models
from odoo.exceptions import UserError

DEP_NOPAY_CODE = 'DEP_NOPAY'
DEP_NOPAY_BASIC_CODE = 'DEP_NOPAY_BASIC'


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def compute_sheet(self):
        self._sync_deputation_input()
        return super().compute_sheet()

    def _deputation_monthly_basic(self):
        """Monthly Basic, as computed by the BASIC rule of ``custom_payslip_report``."""
        self.ensure_one()
        return self.version_id.wage or self.employee_id.l10n_in_basic_salary_amount or 0.0

    def _deputation_monthly_fixed_pay(self):
        """Fixed monthly earnings of the India structure: Basic + Standard + Fixed allowance.

        Mirrors the BASIC, STD and SPL rules of ``custom_payslip_report`` so the
        proration matches what the payslip pays. One-time inputs (bonus, arrears)
        are not prorated.
        """
        self.ensure_one()
        standard = self.version_id.hra or self.employee_id.l10n_in_hra or 0.0
        fixed = self.employee_id.l10n_in_fixed_allowance or 0.0
        return self._deputation_monthly_basic() + standard + fixed

    def _set_input_line(self, code, name, amount):
        self.ensure_one()
        line = self.input_line_ids.filtered(lambda l: l.code == code)
        if line:
            line[:1].write({'amount': amount, 'name': name})
            (line - line[:1]).unlink()
        elif amount:
            self.input_line_ids = [(0, 0, {
                'name': name,
                'code': code,
                'amount': amount,
                'sequence': 60,
                'version_id': self.version_id.id,
            })]

    def _sync_deputation_input(self):
        """Put the pay for days spent on a host country payroll on the deputation inputs.

        DEP_NOPAY: fixed monthly pay x (days on host payroll / calendar days of the period).
        DEP_NOPAY_BASIC: the Basic part of it, so PF is charged only on the Basic paid.
        """
        for slip in self.filtered(lambda s: s.state == 'draft' and not s.credit_note):
            period_days = (slip.date_to - slip.date_from).days + 1
            off_days = slip.employee_id._get_off_home_payroll_days(slip.date_from, slip.date_to)
            if off_days >= period_days:
                raise UserError(self.env._(
                    '%(employee)s is on a host country payroll for the whole period %(start)s - %(end)s. '
                    'No home payslip is due; delete this payslip.',
                    employee=slip.employee_id.name, start=slip.date_from, end=slip.date_to))
            currency = slip.company_id.currency_id
            amount = basic = 0.0
            if off_days:
                amount = currency.round(slip._deputation_monthly_fixed_pay() * off_days / period_days)
                basic = currency.round(slip._deputation_monthly_basic() * off_days / period_days)
            name = self.env._('Deputation: %(off)s of %(total)s days on host payroll',
                              off=off_days, total=period_days)
            slip._set_input_line(DEP_NOPAY_CODE, name, amount)
            slip._set_input_line(DEP_NOPAY_BASIC_CODE, self.env._('%s (Basic part)', name), basic)
