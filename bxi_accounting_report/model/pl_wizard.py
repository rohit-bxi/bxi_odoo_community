from odoo import models, fields

class PLQuarter(models.Model):
    _name = 'pl.quarter'
    name = fields.Char()
    
class PLReportWizard(models.TransientModel):
    _name = 'pl.report.wizard'

    financial_year = fields.Selection([
        ('2025', '2025-2026'),
        ('2026', '2026-2027'),
    ], required=True)
    quarters = fields.Char(
        default="Q1, Q2, Q3, Q4",
        readonly=True
    )
    currency_id = fields.Many2one(
        'res.currency',
        string="Currency",
        default=lambda self: self.env.ref('base.USD'),
        required=True
    )

    company_ids = fields.Many2many(
        'res.company',
        string="Companies",
    )

    def action_open_dashboard(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'custom_pl_dashboard',
            'context': {
                'financial_year': self.financial_year,
                'company_ids': self.company_ids.ids,
                'currency_id': self.currency_id.id,
                'currency_symbol': self.currency_id.symbol,
            }
        }