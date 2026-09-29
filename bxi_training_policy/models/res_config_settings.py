from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── Policy rules (all companies) ─────────────────────────────────────
    trn_lead_days = fields.Integer(
        string='HR Notice (Days)', default=20, config_parameter='bxi_training_policy.lead_days')
    trn_form_days = fields.Integer(
        string='Form Due Before Training (Days)', default=7, config_parameter='bxi_training_policy.form_days')
    trn_agreement_threshold = fields.Float(
        string='Service Agreement Threshold', default=30000,
        config_parameter='bxi_training_policy.agreement_threshold')
    trn_claim_days = fields.Integer(
        string='Claim Due After Training (Days)', default=30, config_parameter='bxi_training_policy.claim_days')
    trn_claim_reminder_days = fields.Integer(
        string='Claim Reminder (Days Before Due)', default=7,
        config_parameter='bxi_training_policy.claim_reminder_days')
    trn_stamp_paper_value = fields.Float(
        string='Stamp Paper Value', default=100, config_parameter='bxi_training_policy.stamp_paper_value')
    trn_agreement_reminder_days = fields.Integer(
        string='Agreement Reminder Interval (Days)', default=3,
        config_parameter='bxi_training_policy.agreement_reminder_days')
    trn_expiry_notice_days = fields.Integer(
        string='Agreement Ending Notice (Days)', default=30,
        config_parameter='bxi_training_policy.expiry_notice_days')

    # ── Company ──────────────────────────────────────────────────────────
    trn_hr_user_id = fields.Many2one(related='company_id.trn_hr_user_id', readonly=False)
    trn_es_user_id = fields.Many2one(related='company_id.trn_es_user_id', readonly=False)
    trn_finance_user_id = fields.Many2one(related='company_id.trn_finance_user_id', readonly=False)
    trn_policy_id = fields.Many2one(related='company_id.trn_policy_id', readonly=False)
    trn_signatory_name = fields.Char(related='company_id.trn_signatory_name', readonly=False)
    trn_accounting_mode = fields.Selection(related='company_id.trn_accounting_mode', readonly=False)
    trn_advance_account_id = fields.Many2one(related='company_id.trn_advance_account_id', readonly=False)
    trn_bonded_account_id = fields.Many2one(related='company_id.trn_bonded_account_id', readonly=False)
    trn_expense_account_id = fields.Many2one(related='company_id.trn_expense_account_id', readonly=False)
    trn_recovery_account_id = fields.Many2one(related='company_id.trn_recovery_account_id', readonly=False)
    trn_journal_id = fields.Many2one(related='company_id.trn_journal_id', readonly=False)
    trn_misc_journal_id = fields.Many2one(related='company_id.trn_misc_journal_id', readonly=False)
