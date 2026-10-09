from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    lc_claim_days = fields.Integer(
        string='Claim Window (Days)', default=45, config_parameter='bxi_local_conveyance.claim_days')
    lc_reminder_days = fields.Integer(
        string='Reminder (Days Before Deadline)', default=7, config_parameter='bxi_local_conveyance.reminder_days')
    lc_office_coverage_months = fields.Integer(
        string='Other Office Coverage (Months)', default=2,
        config_parameter='bxi_local_conveyance.office_coverage_months')
    lc_food_daily_limit = fields.Float(
        string='Food Limit per Day', default=1000, config_parameter='bxi_local_conveyance.food_daily_limit')
    lc_non_working_day_mode = fields.Selection(
        [('block', 'Refuse the claim'), ('flag', 'Send to HR for review')],
        string='Weekends and Holidays', default='block',
        config_parameter='bxi_local_conveyance.non_working_day_mode')
    conveyance_finance_user_id = fields.Many2one(related='company_id.conveyance_finance_user_id', readonly=False)
    conveyance_hr_user_id = fields.Many2one(related='company_id.conveyance_hr_user_id', readonly=False)
