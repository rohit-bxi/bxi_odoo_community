from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError


class BxiSalaryAdvanceInstallment(models.Model):
    """One monthly EMI of a salary advance, deducted through the SAL_ADV payslip input."""
    _name = 'bxi.salary.advance.installment'
    _description = 'Salary Advance EMI'
    _order = 'due_date, sequence, id'

    advance_id = fields.Many2one('bxi.salary.advance', string='Salary Advance', required=True,
                                 ondelete='cascade', index=True)
    employee_id = fields.Many2one(related='advance_id.employee_id', store=True, index=True)
    company_id = fields.Many2one(related='advance_id.company_id', store=True)
    currency_id = fields.Many2one(related='advance_id.currency_id')
    category = fields.Selection(related='advance_id.category', store=True)
    sequence = fields.Integer(string='EMI No.', default=1)
    due_date = fields.Date(string='Payroll Month', required=True, index=True,
                           help="First day of the month whose payroll deducts this EMI.")
    amount = fields.Monetary(string='Amount', currency_field='currency_id', required=True)
    amount_recovered = fields.Monetary(string='Recovered', currency_field='currency_id', readonly=True, copy=False)
    state = fields.Selection(
        [('pending', 'Pending'), ('deducted', 'Deducted')],
        string='Status', default='pending', required=True, index=True, copy=False,
    )
    payslip_id = fields.Many2one('hr.payslip', string='Payslip', readonly=True, copy=False, ondelete='set null',
                                 index='btree_not_null')
    date_recovered = fields.Date(string='Recovered On', readonly=True, copy=False)
    move_id = fields.Many2one('account.move', string='Recovery Entry', readonly=True, copy=False)
    is_fnf = fields.Boolean(string='Full & Final Settlement', readonly=True)
    origin_installment_id = fields.Many2one(
        'bxi.salary.advance.installment', string='Carried Forward From', readonly=True, copy=False,
        ondelete='cascade', help="The net pay could not cover this EMI; the shortfall was carried forward.")

    @api.ondelete(at_uninstall=False)
    def _unlink_except_deducted(self):
        if any(inst.state == 'deducted' for inst in self):
            raise UserError(self.env._("EMIs already deducted from a payslip cannot be deleted."))

    # ── Payroll ──────────────────────────────────────────────────────────
    def _register_recovery(self, payslip, recovered):
        """Allocate the amount deducted by a confirmed payslip to its EMIs, oldest first.

        An EMI the net pay could not fully cover is reduced to what was deducted and the
        shortfall is carried forward to the next payroll month."""
        next_month = payslip.date_to + relativedelta(months=1, day=1)
        remaining = recovered
        for inst in self.sorted(lambda i: (i.due_date, i.sequence, i.id)):
            currency = inst.currency_id
            take = currency.round(min(remaining, inst.amount))
            remaining = currency.round(remaining - take)
            shortfall = currency.round(inst.amount - take)
            if currency.is_zero(take):
                # Nothing deducted: the whole EMI moves to the next payroll.
                inst.write({'due_date': next_month, 'payslip_id': False})
                inst.advance_id._notify_shortfall(payslip, shortfall)
                continue
            vals = {'state': 'deducted', 'amount_recovered': take, 'date_recovered': payslip.date_to}
            if currency.compare_amounts(shortfall, 0) > 0:
                vals['amount'] = take
                inst.advance_id.installment_ids = [Command.create({
                    'sequence': inst.sequence,
                    'due_date': next_month,
                    'amount': shortfall,
                    'is_fnf': inst.is_fnf,
                    'origin_installment_id': inst.id,
                })]
                inst.advance_id._notify_shortfall(payslip, shortfall)
            inst.write(vals)

    def _revert_recovery(self):
        """The payslip that deducted these EMIs was cancelled or reset: they are due again."""
        deducted = self.filtered(lambda i: i.state == 'deducted')
        for move in deducted.move_id.filtered(lambda m: m.state == 'posted'):
            move._reverse_moves([{'ref': self.env._("Reversal of %(ref)s", ref=move.ref)}], cancel=True)
        for inst in deducted:
            carried = self.search([('origin_installment_id', '=', inst.id)])
            if carried.filtered(lambda c: c.state == 'deducted'):
                raise UserError(self.env._(
                    "The shortfall of EMI %(sequence)s of %(advance)s has already been deducted by a later "
                    "payslip. Cancel that payslip first.", sequence=inst.sequence, advance=inst.advance_id.name))
            amount = inst.amount + sum(carried.mapped('amount'))
            carried.unlink()
            inst.write({
                'state': 'pending', 'amount': amount, 'amount_recovered': 0.0,
                'date_recovered': False, 'move_id': False,
            })
