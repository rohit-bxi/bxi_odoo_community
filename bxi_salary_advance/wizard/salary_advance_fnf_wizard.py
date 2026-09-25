from odoo import fields, models
from odoo.exceptions import UserError


class BxiSalaryAdvanceFnfWizard(models.TransientModel):
    _name = 'bxi.salary.advance.fnf.wizard'
    _description = 'Settle Salary Advance in Full & Final Settlement'

    advance_id = fields.Many2one('bxi.salary.advance', string='Salary Advance', required=True)
    last_day = fields.Date(string='Last Working Day', required=True, default=fields.Date.context_today,
                           help="The outstanding balance is deducted from the payroll of this month.")
    reason = fields.Selection(
        [('transfer', 'Transfer / return to base location'), ('separation', 'Separation'), ('other', 'Other')],
        string='Reason', required=True, default='transfer')
    note = fields.Text(string='Note')

    def action_settle(self):
        self.ensure_one()
        advance = self.advance_id
        if advance.state != 'disbursed' or not self.env.user.has_group('bxi_salary_advance.group_salary_advance_hr'):
            raise UserError(self.env._("Only HR can settle an advance being recovered in the Full & Final Settlement."))
        reason = dict(self._fields['reason']._description_selection(self.env)).get(self.reason)
        advance._move_to_fnf(self.last_day, note=self.env._(
            "%(reason)s: the outstanding balance of %(amount)s will be recovered in the Full & Final Settlement "
            "(payroll of %(month)s). %(note)s", reason=reason,
            amount=advance.currency_id.format(advance.amount_balance),
            month=self.last_day.strftime('%B %Y'), note=self.note or ''))
        return {'type': 'ir.actions.act_window_close'}
