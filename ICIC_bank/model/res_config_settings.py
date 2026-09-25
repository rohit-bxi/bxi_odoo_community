from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    icici_api_key = fields.Char(
        related="company_id.icici_api_key",
        string="ICICI API Key",
        readonly=False,
    )

    icici_base_url = fields.Char(
        related="company_id.icici_base_url",
        string="ICICI Base URL",
        readonly=False,
        help="e.g. https://apibankingone.icici.bank.in for Production "
        "or https://apibankingonesandbox.icici.bank.in for Sandbox.",
    )

    icici_corp_id = fields.Char(
        related="company_id.icici_corp_id",
        string="ICICI Corporate ID",
        readonly=False,
    )

    icici_user_id = fields.Char(
        related="company_id.icici_user_id",
        string="ICICI User ID",
        readonly=False,
    )

    icici_urn = fields.Char(
        related="company_id.icici_urn",
        string="ICICI URN",
        readonly=False,
    )

    icici_aggr_id = fields.Char(
        related="company_id.icici_aggr_id",
        string="ICICI Aggregator ID",
        readonly=False,
    )

    icici_aggr_name = fields.Char(
        related="company_id.icici_aggr_name",
        string="ICICI Aggregator Name",
        readonly=False,
    )

    icici_debit_account = fields.Char(
        related="company_id.icici_debit_account",
        string="ICICI Debit Account Number",
        readonly=False,
    )

    icici_debit_branch = fields.Char(
        related="company_id.icici_debit_branch",
        string="ICICI Debit Branch Code",
        readonly=False,
    )
