import base64
import hashlib
from odoo import fields, models, _
from odoo import api
from odoo.exceptions import UserError
import json
import logging
import requests
from odoo.exceptions import UserError
import uuid
from urllib.parse import quote


_logger = logging.getLogger(__name__)

class HrHire(models.Model):
    _inherit = 'hr.applicant'
    _description = "HR Applicant Extension for Offer Letter"

    cur_pre_hr_name = fields.Char("Current/Previous HR Name")
    cur_pre_hr_contact = fields.Char("Current/Previous HR Contact")
    cur_pre_reporting_manager = fields.Char("Current/Previous Reporting Manager Name")
    cur_pre_reporting_manager_contact = fields.Char("Current/Previous Reporting Manager Contact")

    first_interview_id = fields.Many2one('hr.employee',string="First Interviewer")
    second_interview_id = fields.Many2one('hr.employee',string="Second Interviewer")
    final_interview_id = fields.Many2one('hr.employee',string="Final Interviewer")
    first_interview_remark = fields.Text(string="First Interview Remark")
    second_interview_remark = fields.Text(string="Second Interview Remark")
    final_interview_remark = fields.Text(string="Final Interview Remark")
    resume_file = fields.Binary(
        string="Resume",
        attachment=True
    )
    is_application_submitted = fields.Boolean(
        string="Application Submitted",
        default=False
    )
    job_title = fields.Char(string="Job title")
    cover_letter = fields.Text(string="Cover Letter")
    resume_filename = fields.Char(
        string="File Name"
    )

    # OPTIONAL: prevent duplicate emails per stage
    stage_mail_sent_ids = fields.Many2many(
        'hr.recruitment.stage',
        string="Sent Stage Emails"
    )
    template_company_id = fields.Many2one(
        'res.company',
        string='Template Company',
        related='company_id',
        readonly=True,
    )
    job_approach = fields.Char("Job Approach")
    country = fields.Char("Country")
    sign_request_id = fields.Many2one('sign.oca.request', string="Sign Request")

    reporting_manager_id = fields.Many2one('hr.employee', string="Reporting Manager")
    hr_user_id = fields.Many2one('hr.employee', string="HR Responsible")

    father_name = fields.Char("Father Name")
    mother_name = fields.Char("Mother Name")
    contact_number = fields.Char("Contact Number")
    aadhar_number = fields.Char("Aadhar Number")
    pan_number = fields.Char("PAN Number")
    full_address = fields.Char("Full Address")
    joining_date = fields.Date(string="Joining Date")

    # Documents
    doc_10th_id = fields.Many2many(
    'ir.attachment',
    'hr_applicant_doc_10th_rel',
    'applicant_id',
    'attachment_id',
    string="10th Marksheet"
    )

    doc_12th_id = fields.Many2many(
        'ir.attachment',
        'hr_applicant_doc_12th_rel',
        'applicant_id',
        'attachment_id',
        string="12th Marksheet"
    )

    doc_graduation_id = fields.Many2many(
        'ir.attachment',
        'hr_applicant_doc_grad_rel',
        'applicant_id',
        'attachment_id',
        string="Graduation Certificate"
    )

    doc_master_id = fields.Many2many(
        'ir.attachment',
        'hr_applicant_doc_master_rel',
        'applicant_id',
        'attachment_id',
        string="Master Degree Certificate"
        )

    any_certificate = fields.Many2many(
        'ir.attachment',
        'hr_applicant_any_certificate_rel',
        'applicant_id',
        'attachment_id',
        string="Any certificate(if any)"
    )

    photograph = fields.Many2many(
        'ir.attachment',
        'hr_applicant_photo_rel',
        'applicant_id',
        'attachment_id',
        string="Photograph"
    )

    # Experience
    experience_ids = fields.One2many(
        'hr.applicant.experience',
        'applicant_id',
        string="Experience"
    )
    stage_level = fields.Integer(compute="_compute_stage_level")
    offer_letter_attachment_id = fields.Many2one('ir.attachment', string="Offer Letter Attachment")
    externals_form_token = fields.Char("External Form Token")

    revenue_type = fields.Selection([
        ('revenue', 'Revenue'),
        ('simple', 'Simple'),
        ('nonrevenue', 'Non Revenue'),
    ], string="Type", default='revenue', tracking=True)
    # Basic Info
    band = fields.Char("Band")
    department_id = fields.Many2one('hr.department', string="Department")
    emp_skill_category = fields.Char("Skill Category")
    emp_category = fields.Char("Category")
    company_currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True
    )

    # Monthly Components
    basic_salary = fields.Monetary(string="Basic Salary",store=True,currency_field='company_currency_id',readonly=False)
    flexible_allowance = fields.Float("Flexible Allowance", compute="_compute_salary", store=True, readonly=True, compute_sudo=True)

    monthly_total = fields.Float(compute="_compute_salary", store=True, tracking=True,compute_sudo=True,)
    annual_fixed = fields.Float(compute="_compute_salary", store=True, tracking=True,compute_sudo=True,)

    # Retirals
    pf = fields.Float("Provident Fund", default=21600.0, tracking=True)
    insurance = fields.Float("Medical Insurance", default=50000.0, tracking=True)
    nps = fields.Float("NPS", default=15000, tracking=True)

    retiral_total = fields.Float(compute="_compute_salary", store=True, tracking=True,compute_sudo=True,)

    # Variable
    performance_bonus_percentage = fields.Integer(string="Performance Bonus %")
    org_bonus_percentage = fields.Integer(string="Organisation Bonus %")
    org_bonus = fields.Float("Org Bonus", compute="_compute_bonus", tracking=True,readonly=False,store=True)
    performance_bonus = fields.Float("Performance Bonus", compute="_compute_bonus", tracking=True,readonly=False,store=True)

    variable_total = fields.Float(compute="_compute_salary", store=True, tracking=True,readonly=False)

    # Final CTC
    ctc_total = fields.Float(compute="_compute_salary", store=True, tracking=True,readonly=False)

    location_ids = fields.Many2one(
        'hr.work.location',
        string="Job Location"
    )
    work_location_address = fields.Char(
        string="Work Location Address",
        compute="_compute_work_location_address",
        store=False,
    )
    def _compute_work_location_address(self):
        for employee in self:
            employee.work_location_address = (
                employee.location_ids.address
                if employee.location_ids
                else False
            )
    offer_letter_id = fields.Char(
        string="Document ID",
        readonly=True,
        copy=False,
    )

    def _generate_offer_letter_id(self):
        self.ensure_one()

        if not self.offer_letter_id:
            self.offer_letter_id = self.env['ir.sequence'].next_by_code(
                'hr.applicant.offer.letter'
            )

        return self.offer_letter_id
    
    def create_attachment(self, name, data, res_model, res_id):
        if not data:
            return False

        return self.env['ir.attachment'].create({
            'name': name,
            'type': 'binary',
            'datas': data,
            'res_model': res_model,
            'res_id': res_id,
        })


    def _compute_stage_level(self):
        for rec in self:
            if rec.stage_id:
                if rec.stage_id.name == 'First Interview':
                    rec.stage_level = 1
                elif rec.stage_id.name == 'Second Interview':
                    rec.stage_level = 2
                elif rec.stage_id.name == 'Final Interview':
                    rec.stage_level = 3
                elif rec.stage_id.id >= int(3):
                    rec.stage_level = 4
                else:
                    rec.stage_level = 0
            else:
                rec.stage_level = 0

    def _sync_bxi_employee(self):
        Employee = self.env['hr.bxi.employee'].sudo()

        for applicant in self:
            stage_name = (
                (applicant.stage_id.name or '').strip().casefold()
            )

            if stage_name != 'make proposal':
                continue

            employee = Employee.search(
                [('applicant_id', '=', applicant.id)],
                limit=1,
            )

            vals = {
                'applicant_id': applicant.id,
                'name': (
                    applicant.partner_name
                    or applicant.name
                    or 'New Applicant'
                ),
                'contact_number': applicant.partner_phone or False,
                'personal_email': applicant.email_from or False,
                'job_id': applicant.job_id.id or False,
                'job_title': (
                    applicant.job_id.name
                    if applicant.job_id else False
                ),
                'company_id': (
                    applicant.company_id.id
                    if applicant.company_id
                    else self.env.company.id
                ),
                'department_id': (
                    applicant.job_id.department_id.id
                    if applicant.job_id
                    and applicant.job_id.department_id
                    else False
                ),
            }

            if employee:
                employee.write(vals)
            else:
                Employee.create(vals)

    @api.model_create_multi
    def create(self, vals_list):
        applicants = super().create(vals_list)
        applicants._sync_bxi_employee()
        return applicants

    def write(self, vals):
        result = super().write(vals)

        if {
            'stage_id', 'partner_name', 'name',
            'partner_phone', 'email_from', 'job_id', 'company_id'
        }.intersection(vals):
            self._sync_bxi_employee()

        return result

    # ---------------------------------------------------------
    # OFFER LETTER ACTIONS
    # ---------------------------------------------------------
    def action_generate_offer_letter(self):
        self.ensure_one()
        if not self.offer_letter_id:
            self._generate_offer_letter_id()

        if not self.partner_name:
            raise UserError("Please enter Full Name.")

        report = self.env.ref(
            'bxi_hr_recruitment.action_report_offer_letter'
        )
        pdf_content, _ = report._render_qweb_pdf(
            'bxi_hr_recruitment.action_report_offer_letter',
            res_ids=[self.id]
        )

        attachment = self.env['ir.attachment'].create({
            'name': f'Offer Letter - {self.partner_name}.pdf',
            'datas': base64.b64encode(pdf_content),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })

        self.offer_letter_attachment_id = attachment.id

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_view_offer_letter(self):
        self.ensure_one()

        # Ensure latest values
        self._compute_salary()
        self._compute_bonus()

        report = self.env.ref('bxi_hr_recruitment.action_report_offer_letter')

        pdf_content, _ = report._render_qweb_pdf(
            'bxi_hr_recruitment.action_report_offer_letter',
            res_ids=[self.id]
        )
        attachment = self.env['ir.attachment'].create({
            'name': f'Offer Letter - {self.partner_name}.pdf',
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf'
        })

        self.offer_letter_attachment_id = attachment.id

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=false',
            'target': 'self',
        }

    def write(self, vals):
        if 'stage_id' in vals:
            new_stage = self.env['hr.recruitment.stage'].browse(vals.get('stage_id'))
            for rec in self:
                if new_stage.name == 'Second Interview':
                    if not rec.first_interview_remark:
                        raise UserError("⚠ Please fill First Interview Feedback before moving to Second Interview.")

                elif new_stage.name == 'Final Interview':
                    if not rec.second_interview_remark:
                        raise UserError("⚠ Please fill Second Interview Feedback before moving to Final Interview.")

                elif new_stage.name == 'Make Proposal':
                    if not rec.final_interview_remark:
                        raise UserError("⚠ Please fill Final Interview Feedback before moving to Make Proposal.")

        #  STORE OLD STAGES
        old_stages = {rec.id: rec.stage_id.id for rec in self}

        res = super().write(vals)

        if 'stage_id' in vals:

            for rec in self:

                template = None

                old_stage_id = old_stages.get(rec.id)
                old_stage = self.env['hr.recruitment.stage'].browse(old_stage_id)

                if old_stage and rec.stage_id.sequence <= old_stage.sequence:
                    continue

                if rec.stage_id.name == 'Qualification':
                    template = self.env.ref('bxi_hr_recruitment.email_stage_qualification')

                elif rec.stage_id.name == 'First Interview':
                    template = self.env.ref('bxi_hr_recruitment.email_stage_first_interview')

                elif rec.stage_id.name == 'Second Interview':
                    template = self.env.ref('bxi_hr_recruitment.email_stage_second_interview')

                elif rec.stage_id.name == 'Final Interview':
                    template = self.env.ref('bxi_hr_recruitment.email_stage_final_interview')

                elif rec.stage_id.name == 'Make Proposal':
                    template = self.env.ref('bxi_hr_recruitment.email_stage_contract_proposal')

                elif rec.stage_id.name == 'Contract Proposal':
                    template = self.env.ref('bxi_hr_recruitment.email_stage_offer_letter')

                if template:
                    template.send_mail(rec.id, force_send=True)

        return res

    def action_send_application_form(self):
        self.ensure_one()

        if not self.email_from:
            raise UserError(_("Applicant email is missing."))
        
        if not self.job_id:
            raise UserError(
                _("Please select a Job Position before sending the application form.")
            )
        base_url = "https://careers.bxiventures.com/application-form/"

        # Generate secure token (optional for your side)
        token_string = f"{self.id}-{self.create_date}"
        token = hashlib.md5(token_string.encode()).hexdigest()

        # Store token (fix typo also)
        self.externals_form_token = token

        # Get job platform/source name
        company_name = quote(
            self.company_id.name.strip().lower().replace(' ', '')
            if self.company_id else ''
        )

        # Generate URL
        url = (
            f"{base_url}"
            f"?CJM_hired=1"
            f"&odoo_id={self.id}"
            f"&job_platform={company_name}"
        )

        # Send email
        template = self.env.ref(
            'bxi_hr_recruitment.email_template_application_form'
        )

        template.with_context(
            application_url=url
        ).send_mail(
            self.id,
            force_send=True
        )

        return True

    @api.onchange('basic_salary')
    def onchange_basic_salary(self):
        for data in self:
            if data.basic_salary:
                data.flexible_allowance = data.basic_salary * 0.70

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

    def create_employee_from_applicant(self):
        result = super().create_employee_from_applicant()

        Employee = self.env["hr.employee"]
        ExperienceEmployee = self.env["hr.experience.employee"]
        Attachment = self.env["ir.attachment"]

        for applicant in self:
            # ---------------------------------------------------------
            # FIND THE EMPLOYEE CREATED BY ODOO
            # ---------------------------------------------------------
            employee = Employee.browse()

            if isinstance(result, dict) and result.get("res_id"):
                candidate = Employee.browse(result["res_id"]).exists()
                if candidate:
                    employee = candidate

            if not employee:
                employee = Employee.search(
                    [
                        ("name", "=", applicant.partner_name or applicant.name),
                        ("work_email", "=", applicant.email_from),
                    ],
                    order="id desc",
                    limit=1,
                )

            if not employee:
                continue

            # ---------------------------------------------------------
            # COPY RECRUITMENT FIELDS TO EMPLOYEE
            # ---------------------------------------------------------
            employee_vals = {
                'role_band': applicant.band or False,
                'emp_skill_category': applicant.emp_skill_category or False,
                'emp_category': applicant.emp_category or False,
            }

            if applicant.department_id:
                employee_vals['department_id'] = applicant.department_id.id

            
            # ---------------------------------------------------------
            # EMPLOYEE DOCUMENTS
            # ---------------------------------------------------------
            document_fields = [
                "doc_10th_id",
                "doc_12th_id",
                "doc_graduation_id",
                "doc_master_id",
                "any_certificate",
                "photograph",
            ]

            for field_name in document_fields:
                if field_name in applicant._fields and field_name in employee._fields:
                    employee_vals[field_name] = [
                        (6, 0, applicant[field_name].ids)
                    ]

            employee.write(employee_vals)

            # ---------------------------------------------------------
            # EXPERIENCE RECORDS
            # Avoid creating duplicates if the method is called again.
            # ---------------------------------------------------------
            for experience in applicant.experience_ids:
                existing_experience = ExperienceEmployee.search(
                    [
                        ("employee_id", "=", employee.id),
                        ("company_name", "=", experience.company_name),
                    ],
                    limit=1,
                )

                if existing_experience:
                    continue

                experience_vals = {
                    "employee_id": employee.id,
                    "company_name": experience.company_name,
                    "years": experience.years,
                    "bank_statement_id": [
                        (6, 0, experience.bank_statement_id.ids)
                    ],
                    "salary_slip_id": [
                        (6, 0, experience.salary_slip_id.ids)
                    ],
                }

                # -----------------------------------------------------
                # EXPERIENCE CERTIFICATE
                # Source: Binary field
                # Destination: Many2many ir.attachment
                # -----------------------------------------------------
                binary_fields = [
                    ("experience_certificate", "Experience Certificate"),
                    ("joining_letter", "Joining Letter"),
                    ("relieving_letter", "Relieving Letter"),
                ]

                for field_name, attachment_name in binary_fields:
                    binary_data = experience[field_name]

                    if binary_data:
                        attachment = Attachment.create({
                            "name": attachment_name,
                            "type": "binary",
                            "datas": binary_data,
                            "res_model": "hr.experience.employee",
                        })

                        experience_vals[field_name] = [
                            (6, 0, [attachment.id])
                        ]

                ExperienceEmployee.create(experience_vals)

        return result
            
class HrApplicantCompany(models.Model):
    _name = 'hr.applicant.company'
    _description = 'Previous Company'
    name = fields.Char(required=True)

class HrApplicantExperience(models.Model):
    _name = 'hr.applicant.experience'
    _description = 'Applicant Experience'

    applicant_id = fields.Many2one('hr.applicant')
    company_name = fields.Many2one(
            'hr.applicant.company',
            string='Company Name',
            ondelete='set null'
        ) 
    bank_statement_id = fields.Many2many(
        'ir.attachment',
        'hr_applicant_bank_stmt_rel',
        'applicant_id',
        'attachment_id',
        string="Bank Statement"
    )

    salary_slip_id = fields.Many2many(
        'ir.attachment',
        'hr_applicant_salary_slip_rel',
        'applicant_id',
        'attachment_id',
        string="Last 3 Month Salary Slip"
    )
    years = fields.Float("Years")
    experience_certificate = fields.Binary(
        "Experience Letter", attachment=True
    )
    experience_certificate_filename = fields.Char()

    joining_letter = fields.Binary(
        "Offer/Joining Letter", attachment=True
    )
    joining_letter_filename = fields.Char()

    relieving_letter = fields.Binary(
        "Relieving Letter", attachment=True
    )
    relieving_letter_filename = fields.Char()

    other_certificate = fields.Binary(
        "Apprsail Letter", attachment=True
    )
    other_certificate_filename = fields.Char()
