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
        payouts = self.env['bxi.eb.payout']._generate_annual_payouts(
            self.fy_start, self.fy_end, self.employee_ids or None)
        if not payouts:
            raise UserError(_("No payout to generate: every eligible employee already has a processed payout."))
        action = self.env['ir.actions.act_window']._for_xml_id('bxi_equitable_benefit.action_bxi_eb_payout')
        action['domain'] = [('id', 'in', payouts.ids)]
        return action
