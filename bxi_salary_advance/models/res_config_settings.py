from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── Policy limits (all companies) ────────────────────────────────────
    sa_limit_percent = fields.Float(
        string='Advance Limit (% of Monthly Salary)', default=75,
        config_parameter='bxi_salary_advance.limit_percent')
    sa_salary_basis = fields.Selection(
        [('gross', 'Monthly Gross (Basic + HRA + Flexible Allowance)'), ('basic', 'Basic Salary')],
        string='Monthly Salary Basis', default='gross',
        config_parameter='bxi_salary_advance.salary_basis')
    sa_min_service_months = fields.Integer(
        string='Minimum Service (Months)', default=6,
        config_parameter='bxi_salary_advance.min_service_months')
    sa_emergency_installments = fields.Integer(
        string='Emergency EMIs', default=3,
        config_parameter='bxi_salary_advance.emergency_installments')
    sa_housing_tenancies = fields.Char(
        string='Housing Tenancies (Months)', default='6,12',
        config_parameter='bxi_salary_advance.housing_tenancies',
        help="Comma-separated tenancy durations recovered without an exception.")
    sa_housing_limit_percent = fields.Float(
        string='Housing Limit (% of Monthly Salary)', default=0,
        config_parameter='bxi_salary_advance.housing_limit_percent',
        help="Housing advances above this percentage need an exception approval. 0 means no limit.")
    # Stored inverted: a boolean parameter defaulting to True cannot be switched off.
    sa_request_form_optional = fields.Boolean(
        string='Signed Request Form Optional',
        config_parameter='bxi_salary_advance.request_form_optional',
        help="By default the employee must upload the signed Advance Request Form before submitting.")
    sa_hr_sla_days = fields.Integer(
        string='HR Processing Time (Working Days)', default=7,
        config_parameter='bxi_salary_advance.hr_sla_days')
    sa_rm_reminder_days = fields.Integer(
        string='Manager Reminder After (Days)', default=2,
        config_parameter='bxi_salary_advance.rm_reminder_days')
    sa_perquisite_threshold = fields.Float(
        string='Perquisite Threshold', default=20000,
        config_parameter='bxi_salary_advance.perquisite_threshold',
        help="Interest-free advances above this outstanding amount may be a taxable perquisite "
             "in India; such advances are flagged for the payroll team.")

    sa_eligible_employee_types = fields.Char(
        string='Eligible Employee Types', default='employee,worker',
        config_parameter='bxi_salary_advance.eligible_employee_types',
        help="Comma-separated employee types that count as full-time and may apply (employee, worker, "
             "student, trainee, contractor, freelance).")
    # Stored inverted: a boolean parameter defaulting to True cannot be switched off.
    sa_nonprocessing_require_service = fields.Boolean(
        string='Minimum Service for Joining / Transfer Delays',
        config_parameter='bxi_salary_advance.nonprocessing_require_service',
        help="By default the minimum service is waived for Category I advances requested because of "
             "incomplete joining or delayed transfer formalities.")
    sa_outstanding_scope = fields.Selection(
        [('all', 'Every category'), ('emergency', 'Emergency advances only')],
        string='Block When an Advance Is Outstanding', default='all',
        config_parameter='bxi_salary_advance.outstanding_scope',
        help="The policy requires no other outstanding advance for emergency advances. "
             "'Every category' applies the same rule to all requests.")

    # ── Company ──────────────────────────────────────────────────────────
    sa_hr_user_id = fields.Many2one(related='company_id.sa_hr_user_id', readonly=False)
    sa_finance_user_id = fields.Many2one(related='company_id.sa_finance_user_id', readonly=False)
    sa_geo_hr_head_id = fields.Many2one(related='company_id.sa_geo_hr_head_id', readonly=False)
    sa_advance_account_id = fields.Many2one(related='company_id.sa_advance_account_id', readonly=False)
    sa_disbursement_journal_id = fields.Many2one(related='company_id.sa_disbursement_journal_id', readonly=False)
    sa_recovery_account_id = fields.Many2one(related='company_id.sa_recovery_account_id', readonly=False)
    sa_recovery_journal_id = fields.Many2one(related='company_id.sa_recovery_journal_id', readonly=False)
    sa_policy_id = fields.Many2one(related='company_id.sa_policy_id', readonly=False)
    sa_request_form = fields.Binary(related='company_id.sa_request_form', readonly=False)
    sa_request_form_filename = fields.Char(related='company_id.sa_request_form_filename', readonly=False)
