from odoo import api, fields, models

from .salary_advance import NOT_DISBURSED_STATES, RECOVERY_STATES


class EmployeeResignation(models.Model):
    _inherit = 'employee.resignation'

    sa_advance_ids = fields.Many2many(
        'bxi.salary.advance', string='Salary Advances', compute='_compute_sa_advances')
    sa_outstanding_balance = fields.Monetary(
        string='Outstanding Salary Advance', compute='_compute_sa_advances',
        currency_field='sa_currency_id')
    sa_currency_id = fields.Many2one(related='company_id.currency_id', string='Company Currency')

    def _compute_sa_advances(self):
        Advance = self.env['bxi.salary.advance'].sudo()
        for resignation in self:
            advances = Advance.search([
                ('employee_id', '=', resignation.employee_id.id),
                ('state', 'in', RECOVERY_STATES + ('closed',)),
            ]) if resignation.employee_id else Advance
            resignation.sa_advance_ids = advances
            resignation.sa_outstanding_balance = sum(
                advances.filtered(lambda a: a.state in RECOVERY_STATES).mapped('amount_balance'))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered(lambda r: r.state in ('submitted', 'approved'))._sa_on_notice()
        records.filtered(lambda r: r.state == 'approved')._sa_on_approved()
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals.get('state') in ('submitted', 'approved'):
            self._sa_on_notice()
        if vals.get('state') == 'approved':
            self._sa_on_approved()
        return res

    def _sa_on_notice(self):
        """Employees serving notice are not eligible: cancel advances not paid out yet."""
        Advance = self.env['bxi.salary.advance'].sudo()
        for resignation in self:
            Advance.search([
                ('employee_id', '=', resignation.employee_id.id),
                ('state', 'in', NOT_DISBURSED_STATES),
            ])._cancel_for_resignation(resignation)

    def _sa_on_approved(self):
        """Outstanding advances are recovered in the Full & Final Settlement."""
        Advance = self.env['bxi.salary.advance'].sudo()
        for resignation in self:
            last_day = resignation.approved_last_working_day or resignation.last_working_day
            if not last_day:
                continue
            Advance.search([
                ('employee_id', '=', resignation.employee_id.id), ('state', '=', 'disbursed'),
            ])._move_to_fnf(last_day, resignation)

    def action_open_salary_advances(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('bxi_salary_advance.action_bxi_salary_advance')
        action['domain'] = [('id', 'in', self.sa_advance_ids.ids)]
        return action
