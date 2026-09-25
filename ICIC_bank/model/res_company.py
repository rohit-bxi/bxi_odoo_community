from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    icici_api_key = fields.Char(
        string="ICICI API Key",
        company_dependent=True,
    )

    icici_base_url = fields.Char(
        string="ICICI Base URL",
        company_dependent=True,
        help="e.g. https://apibankingone.icici.bank.in for Production "
        "or https://apibankingonesandbox.icici.bank.in for Sandbox.",
    )

    icici_corp_id = fields.Char(
        string="ICICI Corporate ID",
        company_dependent=True,
    )

    icici_user_id = fields.Char(
        string="ICICI User ID",
        company_dependent=True,
    )

    icici_urn = fields.Char(
        string="ICICI URN",
        company_dependent=True,
    )

    icici_aggr_id = fields.Char(
        string="ICICI Aggregator ID",
        company_dependent=True,
    )

    icici_aggr_name = fields.Char(
        string="ICICI Aggregator Name",
        company_dependent=True,
    )

    icici_debit_account = fields.Char(
        string="ICICI Debit Account Number",
        company_dependent=True,
    )

    icici_debit_branch = fields.Char(
        string="ICICI Debit Branch Code",
        company_dependent=True,
    )
