import random
import secrets
import token

from odoo import models, fields, _, api
from odoo.exceptions import UserError
from datetime import date, timedelta

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    version_id = fields.Many2one('hr.version', groups="base.group_user")
    current_version_id = fields.Many2one('hr.version', groups="base.group_user")
    employee_code = fields.Char(string="Employee Code")
    pa_name = fields.Char(string="PA Name")  
    psa = fields.Char(string="PSA")
    disp = fields.Char(string="DISP")
    role_band = fields.Char(string="Role Band")  
    aadhar_card = fields.Char(string="Aadhar Card")
    emp_category = fields.Char(string="EMP Category")
    emp_skill_category = fields.Char(string="EMP Skill Category")
    manager_emp_code = fields.Char(string="Manager EMP Code")
    medical_insurance_no = fields.Char(string="Medical Insurance No.")
    bank_ifsc = fields.Char(string="IFSC Code", compute="_compute_bank_details", inverse="_inverse_bank_details", store=True)
    bank_document = fields.Binary(string="Cancelled Cheque/Passbook Front Page")  
    bank_account_number = fields.Char(string="Bank Acoount Number", compute="_compute_bank_details", inverse="_inverse_bank_details", store=True)
    bank_name = fields.Char(string="Bank Name", compute="_compute_bank_details", inverse="_inverse_bank_details", store=True)
    nps_contribution = fields.Monetary(
        string="NPS Contribution",
        help="Employee NPS contribution amount",
        currency_field="currency_id"
    )  

    # Indian Payroll & Government Identification Fields
    l10n_in_pan = fields.Char(string="PAN Number", help="Permanent Account Number")
    l10n_in_uan = fields.Char(string="UAN Number", help="Universal Account Number for EPF")
    epf_number = fields.Char(string="EPF / PF / Pension No", help="Employee Provident Fund Number")
    pf_number = fields.Char(string="PF Number", compute="_compute_pf_number", inverse="_inverse_pf_number", store=True)
    l10n_in_esic_number = fields.Char(string="ESIC Number", help="Employee State Insurance Corporation Number")
    emp_date_of_joining = fields.Date(string="Date of Joining")
    sex = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    ], string="Gender (Sex)")

    # Standard & Monthly Payroll Computation Fields
    l10n_in_basic_salary_amount = fields.Monetary(string="Basic Salary Amount", currency_field="currency_id")
    l10n_in_hra = fields.Monetary(string="HRA Amount", currency_field="currency_id")
    l10n_in_fixed_allowance = fields.Monetary(string="Flexible / Special Allowance", currency_field="currency_id")
    l10n_in_pf_employer_amount = fields.Monetary(string="Employer EPF Monthly", currency_field="currency_id")
    l10n_in_tds = fields.Monetary(string="Monthly TDS Amount", currency_field="currency_id")

    @api.depends('epf_number')
    def _compute_pf_number(self):
        for rec in self:
            rec.pf_number = rec.epf_number

    def _inverse_pf_number(self):
        for rec in self:
            rec.epf_number = rec.pf_number

    probation_period = fields.Selection(
        [
            ('yes', 'Yes'),
            ('no', 'No'),
        ],
        string="Probation Period",
        default='no'
    )
    trainee_category = fields.Selection(
        [
            ('yes', 'Yes'),
            ('no', 'No'),
        ],
        string="Trainee Category",
        default='no'
    )
    onsite_offshore = fields.Selection(
        [
            ('onsite', 'Onsite'),
            ('offshore', 'Offshore'),
        ],
        string="Onsite/Offshore"
    )
    company_code = fields.Char(string="Company Code")
    employee_ctc = fields.Float(string="Employee Earning (Annual)")

    def get_employee_earning(self):
        for data in self:
            data.employee_ctc = (data.wage)*12

    def _compute_monthly_tds_new_regime(self, annual_ctc):

        if not annual_ctc:
            return 0.0

        STANDARD_DEDUCTION = 75000.0

        # Calculate taxable income
        taxable_income = max(annual_ctc - STANDARD_DEDUCTION, 0.0)

        # Section 87A Rebate: No tax if taxable income is up to ₹12,00,000
        if taxable_income <= 1200000:
            return 0.0

        # New Tax Regime Slabs (FY 2025-26)
        slabs = [
            (400000, 0.00),
            (800000, 0.05),
            (1200000, 0.10),
            (1600000, 0.15),
            (2000000, 0.20),
            (2400000, 0.25),
            (float("inf"), 0.30),
        ]

        tax = 0.0
        previous_limit = 0.0

        # Calculate tax based on slabs
        for limit, rate in slabs:
            if taxable_income > previous_limit:
                taxable_amount = min(taxable_income, limit) - previous_limit
                tax += taxable_amount * rate
                previous_limit = limit
            else:
                break

        # Apply surcharge if applicable
        surcharge = 0.0
        if taxable_income > 50000000:  # Above ₹5 Cr
            surcharge = tax * 0.37
        elif taxable_income > 20000000:  # Above ₹2 Cr
            surcharge = tax * 0.25
        elif taxable_income > 10000000:  # Above ₹1 Cr
            surcharge = tax * 0.15
        elif taxable_income > 5000000:  # Above ₹50 Lakh
            surcharge = tax * 0.10

        tax += surcharge

        # Apply Health & Education Cess (4%)
        tax *= 1.04

        annual_tax = round(tax, 2)
        monthly_tds = round(annual_tax / 12.0, 2)

        return monthly_tds

    def action_calculate_l10n_in_tds_new_regime(self):
        self.get_employee_earning()
        for emp in self:
            emp.l10n_in_tds = emp._compute_monthly_tds_new_regime(emp.employee_ctc)


    meeting_qty = fields.Integer()
    meeting_rate = fields.Float()

    script_qty = fields.Integer()
    script_rate = fields.Float()

    video_qty = fields.Integer()
    video_rate = fields.Float()

    total_amount = fields.Float(
        compute="_compute_total",
        store=True,
    )
    template_company_id = fields.Many2one(
        'res.company',
    )
    month_year = fields.Date(string="Release Month & Year")

    @api.depends(
        'meeting_qty','meeting_rate',
        'script_qty','script_rate',
        'video_qty','video_rate'
    )
    def _compute_total(self):
        for rec in self:
            rec.total_amount = (
                rec.meeting_qty * rec.meeting_rate
                + rec.script_qty * rec.script_rate
                + rec.video_qty * rec.video_rate
            )
    def action_download_contract_payslip(self):
        return self.env.ref(
            'bxi_hr_employee.action_contract_payslip_report'
        ).report_action(self)

    @api.depends('bank_account_ids', 'bank_account_ids.acc_number', 'bank_account_ids.bank_id.name', 'bank_account_ids.bank_id.bic')
    def _compute_bank_details(self):
        for rec in self:
            bank_account = rec.bank_account_ids.filtered(lambda a: a.acc_number)[:1]
            if bank_account:
                rec.bank_account_number = bank_account.acc_number
                rec.bank_name = bank_account.bank_id.name if bank_account.bank_id else False
                rec.bank_ifsc = bank_account.bank_id.bic if bank_account.bank_id else False
            else:
                rec.bank_account_number = False
                rec.bank_name = False
                rec.bank_ifsc = False

    def _inverse_bank_details(self):
        for rec in self:
            if not rec.bank_account_number:
                continue

            partner = rec.work_contact_id or rec.user_id.partner_id
            if not partner:
                partner = self.env['res.partner'].sudo().create({
                    'name': rec.name,
                    'email': rec.work_email or rec.private_email or '',
                    'phone': rec.work_phone or rec.private_phone or '',
                })
                rec.work_contact_id = partner.id

            bank = False
            if rec.bank_name:
                domain = [('name', '=ilike', rec.bank_name)]
                if rec.bank_ifsc:
                    domain = ['|', ('name', '=ilike', rec.bank_name), ('bic', '=ilike', rec.bank_ifsc)]
                bank = self.env['res.bank'].sudo().search(domain, limit=1)
                if not bank:
                    bank = self.env['res.bank'].sudo().create({
                        'name': rec.bank_name,
                        'bic': rec.bank_ifsc or '',
                    })
                elif rec.bank_ifsc and not bank.bic:
                    bank.bic = rec.bank_ifsc

            bank_account = rec.bank_account_ids.filtered(lambda a: a.partner_id == partner)[:1]
            if not bank_account:
                bank_account = self.env['res.partner.bank'].sudo().create([
                    ('partner_id', '=', partner.id),
                    ('acc_number', '=', rec.bank_account_number)
                ], limit=1)

            if bank_account:
                vals = {
                    'acc_number': rec.bank_account_number,
                }
                if bank:
                    vals['bank_id'] = bank.id
                bank_account.sudo().write(vals)
            else:
                vals = {
                    'acc_number': rec.bank_account_number,
                    'partner_id': partner.id,
                }
                if bank:
                    vals['bank_id'] = bank.id
                bank_account = self.env['res.partner.bank'].sudo().create(vals)

            if bank_account not in rec.bank_account_ids:
                rec.write({'bank_account_ids': [(4, bank_account.id)]})
    # portal usage
    portal_token = fields.Char(copy=False)
    portal_token_expiry = fields.Datetime(copy=False)
    portal_otp = fields.Char(copy=False)
    portal_otp_expiry = fields.Datetime(copy=False)
    portal_otp_verified = fields.Boolean(default=False)
    portal_password = fields.Char(copy=False)

    def _generate_registration_token(self):
        self.ensure_one()
        token = secrets.token_urlsafe(32)
        self.write({
            "portal_token": token,
            "portal_token_expiry": fields.Datetime.now() + timedelta(hours=24),
            "portal_otp": False,
            "portal_otp_expiry": False,
            "portal_otp_verified": False,
        })
        return token
    
    def action_send_registration_link(self):
        self.ensure_one()
        if self.active:
            raise UserError(_("Portal access is only available for archived employees."))
        if not self.private_email:
            raise UserError(_("Personal email is not configured."))
        token = self._generate_registration_token()
        base_url = "https://alumni.bxiventures.com/verify-email"
        registration_link = f"{base_url}?token={token}"
        self.env["mail.mail"].sudo().create({
            "subject": "Employee Document Portal",
            "email_to": self.private_email,
            "email_from": "hrsupport@bxitech.com",
            "body_html": f"""
                <p>Hello {self.name},</p>
                <p>Please click below to register.</p>
                <p>After further verification, you will be able to access your documents.</p>
                <p>employee = {self.employee_code}.</p>
                <p>employee name = {self.name}.</p>
                <p>employee email = {self.private_email}.</p>
                <p> your registration token is "{token}" remember it for future use.</p>
                <p>
                    <a href="{registration_link}">
                        Click here to Verify token and register your account.
                    </a>
                </p>
                <p>This link is valid for 24 hours.</p>
            """
        }).send()
        return True
    
    def _portal_login(self, email, password):
        employee = self.search([
            ("private_email", "=", email)
        ], limit=1)
        if not employee:
            return False
        if employee.portal_password != password:
            return False
        return employee


class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    currency_id = fields.Many2one('res.currency', related='employee_id.currency_id')
    employee_code = fields.Char(related='employee_id.employee_code')
    pa_name = fields.Char(related='employee_id.pa_name')
    psa = fields.Char(related='employee_id.psa')
    disp = fields.Char(related='employee_id.disp')
    role_band = fields.Char(related='employee_id.role_band')
    aadhar_card = fields.Char(related='employee_id.aadhar_card')
    emp_category = fields.Char(related='employee_id.emp_category')
    emp_skill_category = fields.Char(related='employee_id.emp_skill_category')
    manager_emp_code = fields.Char(related='employee_id.manager_emp_code')
    medical_insurance_no = fields.Char(related='employee_id.medical_insurance_no')
    bank_ifsc = fields.Char(related='employee_id.bank_ifsc')
    bank_document = fields.Binary(related='employee_id.bank_document')
    bank_account_number = fields.Char(related='employee_id.bank_account_number')
    bank_name = fields.Char(related='employee_id.bank_name')
    nps_contribution = fields.Monetary(related='employee_id.nps_contribution', currency_field='currency_id')
    l10n_in_pan = fields.Char(related='employee_id.l10n_in_pan')
    l10n_in_uan = fields.Char(related='employee_id.l10n_in_uan')
    epf_number = fields.Char(related='employee_id.epf_number')
    pf_number = fields.Char(related='employee_id.pf_number')
    l10n_in_esic_number = fields.Char(related='employee_id.l10n_in_esic_number')
    emp_date_of_joining = fields.Date(related='employee_id.emp_date_of_joining')
    sex = fields.Selection(related='employee_id.sex')
    l10n_in_basic_salary_amount = fields.Monetary(related='employee_id.l10n_in_basic_salary_amount', currency_field='currency_id')
    l10n_in_hra = fields.Monetary(related='employee_id.l10n_in_hra', currency_field='currency_id')
    l10n_in_fixed_allowance = fields.Monetary(related='employee_id.l10n_in_fixed_allowance', currency_field='currency_id')
    l10n_in_pf_employer_amount = fields.Monetary(related='employee_id.l10n_in_pf_employer_amount', currency_field='currency_id')
    l10n_in_tds = fields.Monetary(related='employee_id.l10n_in_tds', currency_field='currency_id')
    probation_period = fields.Selection(related='employee_id.probation_period')
    trainee_category = fields.Selection(related='employee_id.trainee_category')
    onsite_offshore = fields.Selection(related='employee_id.onsite_offshore')
    company_code = fields.Char(related='employee_id.company_code')
    employee_ctc = fields.Float(related='employee_id.employee_ctc')
    meeting_qty = fields.Integer(related='employee_id.meeting_qty')
    meeting_rate = fields.Float(related='employee_id.meeting_rate')
    script_qty = fields.Integer(related='employee_id.script_qty')
    script_rate = fields.Float(related='employee_id.script_rate')
    video_qty = fields.Integer(related='employee_id.video_qty')
    video_rate = fields.Float(related='employee_id.video_rate')
    total_amount = fields.Float(related='employee_id.total_amount')
    template_company_id = fields.Many2one(related='employee_id.template_company_id')
    month_year = fields.Date(related='employee_id.month_year')
    # employee_location_id = fields.Many2one('stock.location', string='Location', readonly=True)
    struct_id = fields.Many2one('hr.payroll.structure', string='Salary Structure', readonly=True)