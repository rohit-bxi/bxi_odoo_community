from odoo import fields, models
from odoo.exceptions import UserError

DEP_NOPAY_CODE = 'DEP_NOPAY'
DEP_NOPAY_BASIC_CODE = 'DEP_NOPAY_BASIC'
DEP_RETRO_CODE = 'DEP_RETRO'
DEP_RETRO_BASIC_CODE = 'DEP_RETRO_BASIC'
DEP_TDS_ADJ_CODE = 'DEP_TDS_ADJ'


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    # Snapshot of the deputation proration, taken when the payslip is computed. Payslips
    # confirmed before a deputation date was known are corrected on a later payslip.
    dep_tracked = fields.Boolean(string='Deputation Tracked', readonly=True, copy=False)
    dep_settled_days = fields.Integer(
        string='Days Settled as Host Payroll', readonly=True, copy=False,
        help='Days of this period accounted for as spent on a host country payroll, '
             'by this payslip and by the corrections of later payslips.')
    dep_day_rate = fields.Float(string='Deputation Day Rate', readonly=True, copy=False)
    dep_basic_day_rate = fields.Float(string='Deputation Basic Day Rate', readonly=True, copy=False)
    dep_tds_day_rate = fields.Float(string='Deputation TDS Day Rate', readonly=True, copy=False)
    dep_retro_line_ids = fields.One2many(
        'bxi.deputation.payslip.retro', 'payslip_id', string='Deputation Corrections', readonly=True)

    def compute_sheet(self):
        self._sync_deputation_input()
        return super().compute_sheet()

    def action_payslip_done(self):
        res = super().action_payslip_done()
        for line in self.filtered(lambda s: s.state == 'done').dep_retro_line_ids:
            line.source_payslip_id.sudo().dep_settled_days += line.days
        return res

    def action_payslip_cancel(self):
        done = self.filtered(lambda s: s.state == 'done')
        res = super().action_payslip_cancel()
        for line in done.dep_retro_line_ids:
            line.source_payslip_id.sudo().dep_settled_days -= line.days
        return res

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

    def _deputation_monthly_tds(self):
        """Monthly TDS charged by the TDS rule, when the structure has one."""
        self.ensure_one()
        if 'TDS' not in self.struct_id._get_parent_structure().rule_ids.mapped('code'):
            return 0.0
        return abs(self.employee_id.l10n_in_tds or 0.0)

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
        DEP_RETRO / DEP_RETRO_BASIC: corrections of confirmed payslips whose days on the host
        payroll changed since (arrival or return confirmed late). Positive recovers pay.
        DEP_TDS_ADJ: the TDS share of the days not paid at home, refunded.
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
            fixed_pay = slip._deputation_monthly_fixed_pay()
            monthly_basic = slip._deputation_monthly_basic()
            monthly_tds = slip._deputation_monthly_tds()
            slip.write({
                'dep_tracked': True,
                'dep_settled_days': off_days,
                'dep_day_rate': fixed_pay / period_days,
                'dep_basic_day_rate': monthly_basic / period_days,
                'dep_tds_day_rate': monthly_tds / period_days,
            })
            amount = currency.round(fixed_pay * off_days / period_days)
            basic = currency.round(monthly_basic * off_days / period_days)
            tds = monthly_tds * off_days / period_days

            slip._sync_deputation_retro_lines()
            retro = slip.dep_retro_line_ids
            tds += sum(retro.mapped('tds_amount'))

            name = self.env._('Deputation: %(off)s of %(total)s days on host payroll',
                              off=off_days, total=period_days)
            slip._set_input_line(DEP_NOPAY_CODE, name, amount)
            slip._set_input_line(DEP_NOPAY_BASIC_CODE, self.env._('%s (Basic part)', name), basic)
            retro_name = self.env._('Deputation correction: %s',
                                    ', '.join(retro.mapped('source_payslip_id.name')) or '-')
            slip._set_input_line(DEP_RETRO_CODE, retro_name, sum(retro.mapped('amount')))
            slip._set_input_line(DEP_RETRO_BASIC_CODE, self.env._('%s (Basic part)', retro_name),
                                 sum(retro.mapped('basic_amount')))
            slip._set_input_line(DEP_TDS_ADJ_CODE, self.env._('TDS on days on host payroll'),
                                 currency.round(tds))

    def _sync_deputation_retro_lines(self):
        """Corrections of the employee's confirmed payslips whose host payroll days changed.

        Payslips confirmed before this module tracked them are left alone.
        """
        self.ensure_one()
        Retro = self.env['bxi.deputation.payslip.retro'].sudo()
        self.sudo().dep_retro_line_ids.unlink()
        sources = self.sudo().search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'done'),
            ('credit_note', '=', False),
            ('dep_tracked', '=', True),
            ('id', '!=', self.id),
        ])
        if not sources:
            return
        pending = Retro.search([
            ('source_payslip_id', 'in', sources.ids),
            ('payslip_id.state', 'in', ('draft', 'verify')),
        ])
        currency = self.company_id.currency_id
        vals_list = []
        for source in sources:
            off_days = self.employee_id._get_off_home_payroll_days(source.date_from, source.date_to)
            days = off_days - source.dep_settled_days - sum(
                pending.filtered(lambda l: l.source_payslip_id == source).mapped('days'))
            if days:
                vals_list.append({
                    'payslip_id': self.id,
                    'source_payslip_id': source.id,
                    'days': days,
                    'amount': currency.round(source.dep_day_rate * days),
                    'basic_amount': currency.round(source.dep_basic_day_rate * days),
                    'tds_amount': currency.round(source.dep_tds_day_rate * days),
                })
        Retro.create(vals_list)


class BxiDeputationPayslipRetro(models.Model):
    """Days of a confirmed payslip re-settled on a later payslip.

    ``days`` > 0: the earlier payslip paid days that turned out to be on the host
    payroll, so the pay is recovered. ``days`` < 0: it withheld days that were
    paid at home after all, so the pay is given back.
    """
    _name = 'bxi.deputation.payslip.retro'
    _description = 'Deputation Payslip Correction'
    _order = 'source_payslip_id'

    payslip_id = fields.Many2one('hr.payslip', string='Correcting Payslip', required=True,
                                 ondelete='cascade', index=True)
    source_payslip_id = fields.Many2one('hr.payslip', string='Corrected Payslip', required=True,
                                        ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='payslip_id.company_id.currency_id')
    days = fields.Integer(string='Days', help='Positive: pay recovered. Negative: pay given back.')
    amount = fields.Monetary(string='Pay')
    basic_amount = fields.Monetary(string='Basic Part')
    tds_amount = fields.Monetary(string='TDS Part')
