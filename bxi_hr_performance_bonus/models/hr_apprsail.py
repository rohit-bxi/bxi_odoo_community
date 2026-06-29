from odoo import models, fields, api, _
# pyrefly: ignore [missing-import]
from odoo.exceptions import UserError, ValidationError


class HrEmployeeAppraisal(models.Model):
    _name = 'hr.employee.appraisal'
    _description = 'Employee Appraisal'
    _rec_name = 'employee_id'
    _inherit = ['mail.thread']

    employee_id = fields.Many2one(
        'hr.employee',
        required=True
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('released', 'Released'),
        ('cancelled', 'Cancelled')
    ], default='draft', tracking=True)
    
    employee_code = fields.Char(
        related='employee_id.employee_code',
        readonly=True,
    )
    company_id = fields.Many2one(
        related='employee_id.company_id',
        readonly=True,
    )
    template_company_id = fields.Many2one(
        'res.company',
    )
    promotion_job_id = fields.Many2one(
        related='employee_id.job_id',
        readonly=False,
        string="Promotion To Role"
    )
    promoted_department_id = fields.Many2one(
        'hr.department',
        string="Promoted Department"
    )
    promoted_job_id = fields.Many2one(
        'hr.job',
        string="Promoted Designation"
    )
    promoted_position = fields.Char(
        string="Promoted Position"
    )
    department_id = fields.Many2one(
        related='employee_id.department_id',
        string="Department"
    )
    release_date = fields.Date()
    effective_date = fields.Date()
    bonus_amount = fields.Integer()
    payout_month = fields.Date()
    appraisal_percentage = fields.Float(string="Appraisal(%)")
    band = fields.Char(
        related='employee_id.role_band',
        readonly=False,
    )
    letter_type = fields.Selection([
        ('bonus_letter', 'Bonus Letter'),
        ('appraisal_promotion_letter', 'Appraisal and Promotion Letter'),
        ('appraisal_letter', 'Appraisal Letter'),
        ('promotion_letter', 'Promotion Letter'),
    ], string='Letter Type')
     # Monthly Components
     
    basic_salary = fields.Monetary(
        string="New Basic Salary",
        compute='_compute_basic_salary',
        store=True,
        readonly=True,
        currency_field='company_currency_id'
    )
    flexible_allowance = fields.Float(
        "Flexible Allowance",
        compute="_compute_salary",
        store=True,
        readonly=True,
        force_save=True,
        compute_sudo=True,
    )

    monthly_total = fields.Float(
        compute="_compute_salary",
        store=True,
        tracking=True,
        compute_sudo=True,
    )

    annual_fixed = fields.Float(
        compute="_compute_salary",
        store=True,
        tracking=True,
        compute_sudo=True,
    )
    pf = fields.Float("Provident Fund", default=21600.0, tracking=True) 
    insurance = fields.Float("Medical Insurance", default=50000.0, tracking=True) 
    nps = fields.Float("NPS", default=15000, tracking=True)
    performance_bonus_percentage = fields.Integer(string="Performance Bonus %")
    org_bonus_percentage = fields.Integer(string="Organisation Bonus %")
    retiral_total = fields.Float(
        compute="_compute_salary",
        store=True,
        tracking=True,
        compute_sudo=True,
    )
    org_bonus = fields.Float("Org Bonus", compute="_compute_bonus", tracking=True,readonly=False,store=True) 
    performance_bonus = fields.Float("Performance Bonus", compute="_compute_bonus", tracking=True,readonly=False,store=True)
    variable_total = fields.Float(
        compute="_compute_salary",
        store=True,
        tracking=True,
        compute_sudo=True,
    )

    ctc_total = fields.Float(
        compute="_compute_salary",
        store=True,
        tracking=True,
        compute_sudo=True,
    )

    revenue_type = fields.Selection([
        ('revenue', 'Revenue'),
        ('simple', 'Simple'),
        ('nonrevenue', 'Non Revenue'),
    ], string="Type", default='revenue', tracking=True)

    current_band = fields.Char(
            related='employee_id.role_band',
            readonly=False,
        )
    current_basic_salary = fields.Monetary(
        string="Basic Salary",
        currency_field='company_currency_id'
    )  
    company_currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True
    )  
    current_flexible_allowance = fields.Float(
        "Flexible Allowance",
        compute="_compute_current_salary",
        store=True,
        readonly=True,
        force_save=True,
        compute_sudo=True,
    )

    current_monthly_total = fields.Float(
        compute="_compute_current_salary",
        store=True,
        tracking=True,
        compute_sudo=True,
    )

    current_annual_fixed = fields.Float(
        compute="_compute_current_salary",
        store=True,
        tracking=True,
        compute_sudo=True,
    )
    current_pf = fields.Float("Provident Fund", default=21600.0, tracking=True) 
    current_insurance = fields.Float("Medical Insurance", default=50000.0, tracking=True) 
    current_nps = fields.Float("NPS", default=15000, tracking=True)
    current_performance_bonus_percentage = fields.Integer(string="Performance Bonus %")
    current_org_bonus_percentage = fields.Integer(string="Organisation Bonus %")
    current_retiral_total = fields.Float(
        compute="_compute_current_salary",
        store=True,
        tracking=True,
        compute_sudo=True,
    )
    current_org_bonus = fields.Float("Org Bonus", compute="_compute_current_bonus", tracking=True,store=True,readonly=False) 
    current_performance_bonus = fields.Float("Performance Bonus", compute="_compute_current_bonus", tracking=True,store=True,readonly=False)
    current_variable_total = fields.Float(
        compute="_compute_current_salary",
        store=True,
        tracking=True,
        compute_sudo=True,
    )

    current_ctc_total = fields.Float(
        compute="_compute_current_salary",
        store=True,
        tracking=True,
        compute_sudo=True,
    )
    @api.depends('current_basic_salary','appraisal_percentage')
    def _compute_basic_salary(self):
        for rec in self:
            rec.basic_salary = rec.current_basic_salary
            if rec.appraisal_percentage:
                rec.basic_salary = (
                    rec.current_basic_salary +
                    (
                        rec.current_basic_salary *
                        rec.appraisal_percentage / 100
                    )
                )

    def action_open_letter_wizard(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': 'Letter Actions',
            'res_model': 'employee.letter.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_appraisal_id': self.id,
            }
        }

    @api.constrains('bonus_amount')
    def _check_bonus_amount(self):
        for rec in self:
            if rec.letter_type == 'bonus_letter':
                if rec.bonus_amount <= 0:
                    raise ValidationError(
                        "Bonus Amount must be greater than 0."
                    )
                
    @api.depends('current_basic_salary','current_pf','current_insurance','current_nps','current_performance_bonus','current_org_bonus')
    def _compute_current_salary(self):
        for rec in self:
            rec.current_flexible_allowance = rec.current_basic_salary * 0.70
            rec.current_monthly_total = (
                rec.current_basic_salary +
                rec.current_flexible_allowance
            )
            rec.current_annual_fixed = rec.current_monthly_total * 12
            rec.current_retiral_total = (
                rec.current_pf +
                rec.current_insurance +
                rec.current_nps
            )
            rec.current_variable_total = (
                rec.current_performance_bonus +
                rec.current_org_bonus
            )

            rec.current_ctc_total = (
                rec.current_annual_fixed +
                rec.current_retiral_total +
                rec.current_variable_total
            )        
    @api.depends('basic_salary','pf','insurance','nps','performance_bonus','org_bonus')
    def _compute_salary(self):
        for rec in self:

            rec.flexible_allowance = rec.basic_salary * 0.70

            rec.monthly_total = (
                rec.basic_salary +
                rec.flexible_allowance
            )

            rec.annual_fixed = rec.monthly_total * 12

            rec.retiral_total = (
                rec.pf +
                rec.insurance +
                rec.nps
            )

            rec.variable_total = (
                rec.performance_bonus +
                rec.org_bonus
            )

            rec.ctc_total = (
                rec.annual_fixed +
                rec.retiral_total +
                rec.variable_total
            )
    
    @api.depends('annual_fixed','retiral_total','performance_bonus_percentage','revenue_type','org_bonus_percentage')
    def _compute_bonus(self):
        for rec in self:
            # Revenue employees
            if rec.revenue_type == 'revenue':
                rec.org_bonus = (
                    (rec.annual_fixed or 0.0)
                    + (rec.retiral_total or 0.0)
                ) * (rec.org_bonus_percentage or 0.0) / 100

                total_amount = (
                    (rec.annual_fixed or 0.0)
                    + (rec.retiral_total or 0.0)
                    + rec.org_bonus
                )

                rec.performance_bonus = (
                    total_amount
                    * (rec.performance_bonus_percentage or 0.0)
                    / 100
                )

            # Non-revenue employees
            elif rec.revenue_type == 'nonrevenue':
                rec.org_bonus = (
                    (rec.annual_fixed or 0.0)
                    + (rec.retiral_total or 0.0)
                ) * (rec.org_bonus_percentage or 0.0) / 100

                rec.performance_bonus = 0.0

            # Simple employees
            elif rec.revenue_type == 'simple':
                # Keep manually entered values
                pass
            
    @api.depends('current_annual_fixed','current_retiral_total','current_performance_bonus_percentage','revenue_type','current_org_bonus_percentage')
    def _compute_current_bonus(self):
        for rec in self:
            # Revenue employees
            if rec.revenue_type == 'revenue':
                rec.current_org_bonus = (
                    (rec.current_annual_fixed or 0.0)
                    + (rec.current_retiral_total or 0.0)
                ) * (rec.current_org_bonus_percentage or 0.0) / 100

                total_amount = (
                    (rec.current_annual_fixed or 0.0)
                    + (rec.current_retiral_total or 0.0)
                    + rec.current_org_bonus
                )

                rec.current_performance_bonus = (
                    total_amount
                    * (rec.current_performance_bonus_percentage or 0.0)
                    / 100
                )

            # Non-revenue employees
            elif rec.revenue_type == 'nonrevenue':
                rec.current_org_bonus = (
                    (rec.current_annual_fixed or 0.0)
                    + (rec.current_retiral_total or 0.0)
                ) * (rec.current_org_bonus_percentage or 0.0) / 100

                rec.current_performance_bonus = 0.0

            # Simple employees
            elif rec.revenue_type == 'simple':
                # Keep manually entered values
                pass