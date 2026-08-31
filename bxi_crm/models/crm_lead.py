from odoo import api, fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    company_currency = fields.Many2one(
        "res.currency",
        string="Currency",
        compute="_compute_company_currency",
        readonly=True,
    )

    presales_poc_id = fields.Many2one(
        "presales.poc",
        string="Presales POC",
    )

    contract_ids = fields.One2many(
        "project.contract.management",
        "lead_id",
        string="Contracts",
    )

    contract_count = fields.Integer(
        compute="_compute_contract_count",
        string="Contracts",
    )

    @api.depends("company_id")
    def _compute_company_currency(self):
        usd_currency = (
            self.env.ref("base.USD", raise_if_not_found=False)
            or self.env["res.currency"].search([("name", "=", "USD")], limit=1)
            or self.env.company.currency_id
        )
        for lead in self:
            lead.company_currency = usd_currency

    @api.depends("contract_ids")
    def _compute_contract_count(self):
        for rec in self:
            rec.contract_count = len(rec.contract_ids)

    def action_create_contract(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": "Create Contract",
            "res_model": "project.contract.management",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_lead_id": self.id,
                "default_contract_amount": self.expected_revenue,
                "default_client_ids": [(6, 0, self.partner_id.ids)],
            },
        }

    def action_view_contracts(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": "Contracts",
            "res_model": "project.contract.management",
            "view_mode": "list,form",
            "domain": [("lead_id", "=", self.id)],
            "context": {
                "default_lead_id": self.id,
            },
        }