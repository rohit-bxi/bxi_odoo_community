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
    eb_fnf_rating = fields.Selection(
        [('latest', 'Use the latest available rating'), ('required', "Require the separation year's rating")],
        string='Rating on Separation', default='latest',
        help="A separating employee rarely has a rating for the current year yet.",
        config_parameter='bxi_equitable_benefit.fnf_rating')
    eb_absence_source = fields.Selection(
        [('attendance', 'Attendance and flagged leave types'), ('leave', 'Flagged leave types only')],
        string='Unauthorized Absence Source', default='attendance',
        help="Attendance counts working days with neither attendance nor approved leave, "
             "from the first day attendance was recorded for the employee.",
        config_parameter='bxi_equitable_benefit.absence_source')
    eb_min_pattern_compliance = fields.Float(
        string='Minimum Pattern Compliance (%)',
        help="Flag payouts whose office attendance is below this share of the days the work pattern "
             "expects, or whose odd shift pattern was worked on an odd shift working schedule for less than this "
             "share of the days. 0 disables the check. It never blocks the payout.",
        config_parameter='bxi_equitable_benefit.min_pattern_compliance')
    eb_payout_tds = fields.Selection(
        [('incremental', 'Deduct tax at the marginal slab'), ('none', 'No separate deduction')],
        string='TDS on Payout', default='incremental',
        config_parameter='bxi_equitable_benefit.payout_tds')
    eb_auto_generate_days = fields.Integer(
        string='Generate Payouts After (Days)',
        help="Create the draft annual payouts this many days after the financial year closes. 0 disables it.",
        config_parameter='bxi_equitable_benefit.auto_generate_days')
    eb_suspended_from = fields.Date(related='company_id.eb_suspended_from', readonly=False)
