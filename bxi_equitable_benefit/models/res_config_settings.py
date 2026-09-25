from odoo import fields, models

from .eb_eligibility import RATINGS


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    eb_fy_start_month = fields.Integer(
        string='Financial Year Start Month', default=4,
        config_parameter='bxi_equitable_benefit.fy_start_month')
    eb_proration_basis = fields.Selection(
        [('months', 'Calendar Months'), ('days', 'Calendar Days')],
        string='Pro-rata Basis', default='months',
        config_parameter='bxi_equitable_benefit.proration_basis')
    eb_min_rating = fields.Selection(
        RATINGS, string='Minimum Performance Rating', default='meets',
        config_parameter='bxi_equitable_benefit.min_rating')
    eb_allow_missing_rating = fields.Boolean(
        string='Allow Missing Rating',
        help="Do not block the payout when no performance rating is recorded for the year.",
        config_parameter='bxi_equitable_benefit.allow_missing_rating')
    eb_max_unauthorized_days = fields.Float(
        string='Max Unauthorized Absence Days', default=3,
        config_parameter='bxi_equitable_benefit.max_unauthorized_days')
    eb_unpaid_leave_threshold_days = fields.Float(
        string='Long Unpaid Leave Threshold (Days)', default=30,
        config_parameter='bxi_equitable_benefit.unpaid_leave_threshold_days')
