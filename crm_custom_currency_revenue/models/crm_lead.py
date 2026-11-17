from odoo import api, fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    company_currency = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        compute='_compute_company_currency',
        store=True,
        readonly=False,
        precompute=True,
        help='Select Currency (e.g. INR, AED, USD) to display its symbol beside Expected Revenue.',
    )
    base_amount = fields.Float(
        string='Base Value',
        digits='Product Price',
        default=0.0,
        help='Enter the base float value to multiply with the Multiplier / Rate.',
    )
    multiplier_rate = fields.Float(
        string='Multiplier / Rate',
        digits=(12, 4),
        default=1.0,
        help='Float multiplier applied to Base Value to calculate Expected Revenue.',
    )

    @api.depends('company_id')
    def _compute_company_currency(self):
        for lead in self:
            if not lead.company_currency:
                lead.company_currency = lead.company_id.currency_id or self.env.company.currency_id

    @api.onchange('base_amount', 'multiplier_rate')
    def _onchange_calculate_expected_revenue(self):
        for lead in self:
            # If user entered Expected Revenue first and then changed Multiplier, capture Expected Revenue as Base Value
            if not lead.base_amount and lead.expected_revenue and lead.multiplier_rate != 1.0:
                lead.base_amount = lead.expected_revenue
            if lead.base_amount:
                lead.expected_revenue = lead.base_amount * lead.multiplier_rate

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            base = vals.get('base_amount', 0.0)
            rate = vals.get('multiplier_rate', 1.0)
            if base and 'expected_revenue' not in vals:
                vals['expected_revenue'] = base * rate
            elif base and vals.get('expected_revenue') in (0.0, False, None):
                vals['expected_revenue'] = base * rate
        return super().create(vals_list)

    def write(self, vals):
        for lead in self:
            base = vals.get('base_amount', lead.base_amount)
            rate = vals.get('multiplier_rate', lead.multiplier_rate)
            if ('base_amount' in vals or 'multiplier_rate' in vals) and base and 'expected_revenue' not in vals:
                vals = dict(vals, expected_revenue=base * rate)
                super(CrmLead, lead).write(vals)
            else:
                super(CrmLead, lead).write(vals)
        return True
