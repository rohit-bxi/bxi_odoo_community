# -*- coding: utf-8 -*-
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .hdfc_bank_config import ACCOUNT_RE, IFSC_RE
from .hdfc_payout_line import ACTIVE_LINE_STATES


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    hdfc_line_ids = fields.One2many('hdfc.payout.line', 'payslip_id', string='HDFC Payout Lines', copy=False)
    hdfc_payment_state = fields.Selection([
        ('not_paid', 'Not Paid'),
        ('in_batch', 'In Batch'),
        ('processing', 'Processing'),
        ('partially_paid', 'Partially Paid'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('reversed', 'Reversed'),
    ], string='HDFC Payment', compute='_compute_hdfc_payment', store=True, index=True, copy=False)
    hdfc_utr = fields.Char(string='HDFC UTR', compute='_compute_hdfc_payment', store=True)
    hdfc_batch_id = fields.Many2one('hdfc.payout.batch', string='HDFC Batch', compute='_compute_hdfc_payment', store=True)

    @api.depends('hdfc_line_ids.state', 'hdfc_line_ids.utr')
    def _compute_hdfc_payment(self):
        for slip in self:
            lines = slip.hdfc_line_ids.filtered(lambda l: l.state != 'cancelled')
            active = lines.filtered(lambda l: l.state in ACTIVE_LINE_STATES)
            paid = active.filtered(lambda l: l.state == 'paid')
            if active:
                if paid == active:
                    state = 'paid'
                elif paid:
                    state = 'partially_paid'
                elif active.filtered(lambda l: l.state in ('submitted', 'processing')):
                    state = 'processing'
                else:
                    state = 'in_batch'
                batch = active.sorted('id')[-1:].batch_id
            elif lines:
                last = lines.sorted('id')[-1:]
                state = 'reversed' if last.state == 'reversed' else 'failed'
                batch = last.batch_id
            else:
                state, batch = 'not_paid', False
            slip.hdfc_payment_state = state
            slip.hdfc_batch_id = batch
            slip.hdfc_utr = ', '.join(paid.filtered('utr').mapped('utr')) or False

    # ------------------------------------------------------------
    # Release
    # ------------------------------------------------------------

    def action_hdfc_release(self):
        slips = self.filtered(lambda s: s.hdfc_payment_state in ('not_paid', 'failed', 'reversed'))
        if not slips:
            raise UserError(_('The selected payslips are already paid or in an active HDFC batch.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pay via HDFC'),
            'res_model': 'hdfc.release.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_payslip_ids': [fields.Command.set(self.ids)]},
        }

    def _hdfc_prepare_payout(self):
        """Validate the payslips and prepare payout line values.

        :return: ``(lines_by_config, errors)`` where ``lines_by_config`` maps an
            ``hdfc.bank.config`` record to a list of ``hdfc.payout.line`` values.
            All problems are collected so the user can fix them in one pass.
        """
        errors = []
        lines_by_config = {}
        configs = {}
        for company in self.company_id:
            config = self.env['hdfc.bank.config']._get_for_company(company)
            if not config:
                errors.append(_('%s: no active HDFC configuration.', company.name))
            else:
                errors += ['%s: %s' % (company.name, msg) for msg in config._get_setup_errors()]
            configs[company] = config

        for slip in self:
            name = '%s (%s)' % (slip.employee_id.name, slip.number or slip.name)
            config = configs[slip.company_id]
            if slip.state != 'done':
                errors.append(_('%s: the payslip must be done.', name))
                continue
            if slip.credit_note:
                errors.append(_('%s: refund payslips cannot be paid.', name))
                continue
            if slip.currency_id.compare_amounts(slip.net_wage, 0.0) <= 0:
                errors.append(_('%s: the net salary must be positive.', name))
                continue
            if slip.hdfc_payment_state not in ('not_paid', 'failed', 'reversed'):
                errors.append(_('%(slip)s: already in HDFC batch %(batch)s.', slip=name, batch=slip.hdfc_batch_id.name))
                continue
            if not config:
                continue
            split, slip_errors = slip._hdfc_split_amount(config)
            if slip_errors:
                errors += ['%s: %s' % (name, msg) for msg in slip_errors]
                continue
            lines_by_config.setdefault(config, [])
            for bank_account, amount in split:
                ifsc = (bank_account.bank_id.bic or '').strip().upper()
                lines_by_config[config].append({
                    'payslip_id': slip.id,
                    'employee_id': slip.employee_id.id,
                    'partner_id': slip.employee_id.work_contact_id.id,
                    'bank_account_id': bank_account.id,
                    'account_number': re.sub(r'\s', '', bank_account.acc_number or ''),
                    'ifsc': ifsc,
                    'beneficiary_name': bank_account.acc_holder_name or slip.employee_id.name,
                    'amount': amount,
                    'txn_type': config._get_txn_type(ifsc, amount),
                    'narration': slip._hdfc_narration(config),
                })
        return lines_by_config, errors

    def _hdfc_split_amount(self, config):
        """Split the net salary across the employee's bank accounts.

        Follows ``hr.employee.salary_distribution``: fixed amounts first (in
        sequence order), then percentages of what remains; rounding goes to the
        last percentage account.

        :return: ``([(res.partner.bank, amount)], errors)``
        """
        self.ensure_one()
        employee = self.employee_id
        currency = self.currency_id
        accounts = employee.bank_account_ids
        if not accounts:
            return [], [_('no bank account configured.')]

        errors = []
        for account in accounts:
            label = account.acc_number or _('(no number)')
            number = re.sub(r'\s', '', account.acc_number or '')
            if not ACCOUNT_RE.match(number):
                errors.append(_('bank account %s must contain 9 to 18 digits.', label))
            if not IFSC_RE.match((account.bank_id.bic or '').strip().upper()):
                errors.append(_('bank account %s has no valid IFSC (set it as the bank BIC).', label))
            if config.require_trusted_accounts and not account.allow_out_payment:
                errors.append(_('bank account %s is not trusted (enable Send Money).', label))
        if errors:
            return [], errors

        distribution = employee.salary_distribution or {}
        if len(accounts) == 1 or not distribution:
            return [(employee.primary_bank_account_id or accounts[:1], currency.round(self.net_wage))], []

        def info(account):
            return distribution.get(str(account.id), {})

        ordered = accounts.sorted(key=lambda a: info(a).get('sequence', float('inf')))
        fixed = ordered.filtered(lambda a: not info(a).get('amount_is_percentage', True))
        percentage = ordered - fixed

        split = []
        remaining = currency.round(self.net_wage)
        for account in fixed:
            amount = currency.round(min(info(account).get('amount', 0.0), remaining))
            if currency.compare_amounts(amount, 0.0) > 0:
                split.append((account, amount))
                remaining = currency.round(remaining - amount)
        base = remaining
        for index, account in enumerate(percentage, start=1):
            if index == len(percentage):
                amount = remaining
            else:
                amount = currency.round(base * info(account).get('amount', 0.0) / 100.0)
            if currency.compare_amounts(amount, 0.0) > 0:
                split.append((account, amount))
                remaining = currency.round(remaining - amount)
        if currency.compare_amounts(remaining, 0.0) > 0:
            if not split:
                return [(employee.primary_bank_account_id or accounts[:1], remaining)], []
            account, amount = split[-1]
            split[-1] = (account, currency.round(amount + remaining))
        return split, []

    def _hdfc_narration(self, config):
        self.ensure_one()
        template = config.narration_template or 'Salary {period}'
        try:
            return template.format(
                period=self.date_to.strftime('%b %Y') if self.date_to else '',
                employee=self.employee_id.name,
                payslip=self.number or '',
            )
        except (KeyError, IndexError, ValueError):
            return 'Salary'
