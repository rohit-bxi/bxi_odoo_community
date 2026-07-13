from odoo import models, fields, _, api
from odoo.exceptions import UserError
from datetime import date

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

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
                bank_account = self.env['res.partner.bank'].sudo().search([
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