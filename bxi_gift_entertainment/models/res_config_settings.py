from odoo import fields, models

PREFIX = 'bxi_gift_entertainment.'


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    gift_band_order = fields.Char(
        string='Band Order', config_parameter=PREFIX + 'band_order',
        help="Role bands from the most junior to the most senior, comma separated (e.g. E1,E2,E3,E4).")
    gift_min_skip_manager_band = fields.Char(
        string='Minimum Band of the Skip-Level Approver', config_parameter=PREFIX + 'min_skip_manager_band')
    gift_lso_email = fields.Char(string='LSO Mailbox', config_parameter=PREFIX + 'lso_email')
    gift_committee_quorum = fields.Integer(string='Ethics Committee Quorum',
                                           config_parameter=PREFIX + 'committee_quorum')
    gift_seasonal_limit_usd = fields.Float(string='Seasonal Gift Limit (USD)',
                                           config_parameter=PREFIX + 'seasonal_limit_usd')
    gift_donation_single_limit_usd = fields.Float(string='Single Donation Limit (USD)',
                                                  config_parameter=PREFIX + 'donation_single_limit_usd')
    gift_donation_due_diligence_above = fields.Float(string='Donation Due Diligence Above (USD)',
                                                     config_parameter=PREFIX + 'donation_due_diligence_above')
    gift_donation_direct_pay_above = fields.Float(
        string='Donations Paid Directly Above (USD)', config_parameter=PREFIX + 'donation_direct_pay_above',
        help="Donations up to this value are paid by the employee and reimbursed; above it BXI pays through "
             "EdgeFi. 0: every donation is paid directly.")
    gift_donation_claim_days = fields.Integer(string='Donation Claim Window (Days)',
                                              config_parameter=PREFIX + 'donation_claim_days')
    gift_return_due_days = fields.Integer(string='Days to Return a Gift', config_parameter=PREFIX + 'return_due_days')
    gift_approval_reminder_days = fields.Integer(string='Approval Reminder After (Days)',
                                                 config_parameter=PREFIX + 'approval_reminder_days')
