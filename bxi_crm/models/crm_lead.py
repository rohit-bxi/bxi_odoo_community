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

    # -------------------------------------------------------------------------
    # CRM → Partner: set customer_type = 'prospect' (or 'customer' if won)
    # -------------------------------------------------------------------------
    def _handle_partner_assignment(self, force_partner_id=False, create_missing=True):
        """Override to mark newly created CRM partners as 'prospect' (or 'customer' if already won)."""
        # Capture partners that already exist before the assignment
        partners_before = {lead.partner_id for lead in self if lead.partner_id}

        super()._handle_partner_assignment(
            force_partner_id=force_partner_id,
            create_missing=create_missing,
        )

        for lead in self:
            partner = lead.partner_id
            if partner and partner not in partners_before:
                if lead.stage_id.is_won or lead.probability == 100:
                    partner.sudo().write({'customer_type': 'customer'})
                else:
                    partner.sudo().write({'customer_type': 'prospect'})

    # -------------------------------------------------------------------------
    # Opportunity Won → set partner customer_type = 'customer'
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._promote_partner_to_customer()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._promote_partner_to_customer()
        return res

    def _promote_partner_to_customer(self):
        """Promote opportunity's partner from 'prospect' to 'customer' if lead is won."""
        for lead in self:
            if lead.stage_id.is_won or lead.probability == 100:
                if not lead.partner_id and (lead.partner_name or lead.contact_name or lead.email_from):
                    lead._handle_partner_assignment(create_missing=True)
                if lead.partner_id:
                    partners = lead.partner_id | lead.partner_id.commercial_partner_id
                    for p in partners:
                        if p.customer_type == 'vendor':
                            p.sudo().write({'customer_type': 'customer_and_vendor'})
                        elif p.customer_type not in ('customer', 'customer_and_vendor'):
                            p.sudo().write({'customer_type': 'customer'})

    def action_set_won(self):
        """Override to promote partner customer_type to 'customer' on won."""
        result = super().action_set_won()
        self._promote_partner_to_customer()
        return result

    def action_set_won_rainbowman(self):
        """Override to promote partner customer_type to 'customer' on won (rainbowman path)."""
        result = super().action_set_won_rainbowman()
        self._promote_partner_to_customer()
        return result

    def _convert_usd_to_target_currency(self, usd_amount, target_currency, target_date=None):
        if not usd_amount or not target_currency:
            return usd_amount or 0.0

        currency_code = target_currency.name or ""
        d = target_date or fields.Date.context_today(self)
        year = d.year if hasattr(d, "year") else fields.Date.today().year

        if year >= 2027:
            rate_usd_inr = 93.0
            rate_aed_inr = 25.6
        else:
            rate_usd_inr = 90.0
            rate_aed_inr = 24.5

        if currency_code == "USD":
            converted = usd_amount
        elif currency_code == "INR":
            converted = usd_amount * rate_usd_inr
        elif currency_code == "AED":
            converted = (usd_amount * rate_usd_inr) / rate_aed_inr
        else:
            usd_curr = (
                self.env.ref("base.USD", raise_if_not_found=False)
                or self.env["res.currency"].search([("name", "=", "USD")], limit=1)
            )
            if usd_curr and usd_curr != target_currency:
                converted = usd_curr._convert(
                    usd_amount,
                    target_currency,
                    self.company_id or self.env.company,
                    d,
                )
            else:
                converted = usd_amount

        return target_currency.round(converted) if hasattr(target_currency, "round") else round(converted, 2)

    def action_create_contract(self):
        self.ensure_one()

        company = self.company_id or self.env.company
        target_currency = company.currency_id

        contract_amount = self._convert_usd_to_target_currency(
            self.expected_revenue,
            target_currency,
        )

        return {
            "type": "ir.actions.act_window",
            "name": "Create Contract",
            "res_model": "project.contract.management",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_lead_id": self.id,
                "default_currency_id": target_currency.id if target_currency else False,
                "default_contract_amount": contract_amount,
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
