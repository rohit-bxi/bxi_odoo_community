from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BxiEbGeneratePayoutWizard(models.TransientModel):
    _name = 'bxi.eb.generate.payout.wizard'
    _description = 'Generate Equitable Benefit Payouts'

    reference_date = fields.Date(
        string='Any Date in the Financial Year', required=True,
        default=lambda self: fields.Date.context_today(self))
    fy_start = fields.Date(compute='_compute_fy', string='Financial Year Start')
    fy_end = fields.Date(compute='_compute_fy', string='Financial Year End')
    employee_ids = fields.Many2many(
        'hr.employee', string='Employees',
        help="Leave empty to generate for every employee with an approved assignment in the year.")

    @api.depends('reference_date')
    def _compute_fy(self):
        Payout = self.env['bxi.eb.payout']
        for wizard in self:
            wizard.fy_start, wizard.fy_end = Payout._get_fy_bounds(wizard.reference_date or fields.Date.today())

    def action_generate(self):
        self.ensure_one()
        Payout = self.env['bxi.eb.payout']
        domain = [
            ('state', '=', 'approved'),
            ('date_from', '<=', self.fy_end),
            '|', ('date_to', '=', False), ('date_to', '>=', self.fy_start),
        ]
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        employees = self.env['bxi.eb.assignment'].search(domain).employee_id
        existing = Payout.search([
            ('fy_start', '=', self.fy_start),
            ('employee_id', 'in', employees.ids),
            ('state', 'not in', ('rejected', 'cancelled')),
        ])
        drafts = existing.filtered(lambda p: p.state == 'draft')
        new = Payout.create([{
            'employee_id': employee.id,
            'payout_type': 'annual',
            'fy_start': self.fy_start,
            'fy_end': self.fy_end,
            'period_end': self.fy_end,
        } for employee in employees - existing.employee_id])
        payouts = new | drafts
        if not payouts:
            raise UserError(_("No payout to generate: every eligible employee already has a processed payout."))
        payouts.action_compute()
        action = self.env['ir.actions.act_window']._for_xml_id('bxi_equitable_benefit.action_bxi_eb_payout')
        action['domain'] = [('id', 'in', payouts.ids)]
        return action
