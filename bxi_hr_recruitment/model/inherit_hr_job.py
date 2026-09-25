import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError
_logger = logging.getLogger(__name__)


class HrJob(models.Model):
    _inherit = 'hr.job'

    location_type = fields.Selection([
        ('all', 'All Locations'),
        ('multiple', 'Select Multiple'),
        ('specific', 'Specific Location (Udaipur)')
    ], string="Location Type", default='all')

    location_ids = fields.Many2many(
        'hr.location',
        string="Job Locations"
    )

    employee_category = fields.Char(
        string="Employee Category"
    )

    billed_unbilled = fields.Selection([
        ('billed', 'Billed'),
        ('unbilled', 'Unbilled')
    ], string="Billed / Unbilled")

    job_category = fields.Selection([
        ('administration', 'Administration'),
        ('alliances', 'Alliances and Partnerships'),
        ('customer_support', 'Customer Support'),
        ('data_analytics', 'Data & Analytics'),
        ('design_creative', 'Design & Creative'),
        ('development', 'Development'),
        ('digital_marketing', 'Digital Marketing'),
        ('engineering', 'Engineering (Software/Hardware)'),
        ('executive_leadership', 'Executive Leadership'),
        ('finance_accounting', 'Finance And Accounting'),
        ('global_sales', 'Global Sales'),
        ('hospitality', 'Hospitality'),
        ('hr', 'Human Resources'),
        ('inside_sales', 'Inside Sales'),
        ('internship', 'Internship / Trainee'),
        ('it', 'IT'),
        ('legal', 'Legal & Compliance'),
        ('marketing', 'Marketing'),
        ('martech', 'Martech'),
        ('new_business', 'New Business'),
        ('nzeroone', 'nZeroOne'),
        ('operations', 'Operations & Supply Chain'),
        ('other', 'Other'),
        ('practice', 'Practice'),
        ('procurement', 'Procurement'),
        ('product_management', 'Product Management'),
        ('qa', 'Quality Assurance'),
        ('rnd', 'Research & Development'),
        ('sales_bd', 'Sales & Business Development'),
        ('social_media', 'Social Media'),
        ('talent_management', 'Talent Management'),
        ('technology', 'Technology'),
        ('training', 'Training & Development'),
        ('mining_iot', 'Mining IoT Solutions'),
    ], string="Job Category")

    target_date = fields.Date(string="Target Date")
    job_company_id = fields.Many2one('res.company', string="Job Platform")

    salary = fields.Char(string="Salary")
    min_experience = fields.Float(string="Min Experience (Years)")
    max_experience = fields.Float(string="Max Experience (Years)")

    status = fields.Selection([
        ('open', 'Open'),
        ('active', 'Active / Accepting Applications'),
        ('on_hold', 'On Hold'),
        ('closed', 'Closed'),
        ('filled', 'Filled'),
        ('cancelled', 'Cancelled'),
        ('under_review', 'Under Review'),
        ('interviewing', 'Interviewing'),
        ('shortlisting', 'Shortlisting in Progress'),
    ], string="Status", default='open')



    @api.onchange('location_type')
    def _onchange_location_type(self):
        if self.location_type == 'all':
            # select all locations
            locations = self.env['hr.location'].search([])
            self.location_ids = [(6, 0, locations.ids)]

        elif self.location_type == 'specific':
            # select only Udaipur
            udaipur = self.env['hr.location'].search([('name', '=', 'Udaipur')], limit=1)
            self.location_ids = [(6, 0, udaipur.ids)]

        elif self.location_type == 'multiple':
            # allow manual selection
            self.location_ids = [(5, 0, 0)]


    requisition_id = fields.Char(
        string="Requisition ID",
        copy=False,
        readonly=True,
        index=True,
        default='New'
    )

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence']
        for vals in vals_list:
            if not vals.get('requisition_id') or vals.get('requisition_id') == 'New':
                vals['requisition_id'] = sequence.next_by_code(
                    'hr.job.requisition'
                ) or 'New'
        return super().create(vals_list)

class HrJob(models.Model):
    _inherit = 'hr.job'

    location_type = fields.Selection([
        ('all', 'All Locations'),
        ('multiple', 'Select Multiple'),
        ('specific', 'Specific Location (Udaipur)')
    ], string="Location Type", default='all')

    location_ids = fields.Many2many(
        'hr.location',
        string="Job Locations"
    )

    employee_category = fields.Char(
        string="Employee Category"
    )

    @api.onchange('location_type')
    def _onchange_location_type(self):
        if self.location_type == 'all':
            # select all locations
            locations = self.env['hr.location'].search([])
            self.location_ids = [(6, 0, locations.ids)]

        elif self.location_type == 'specific':
            # select only Udaipur
            udaipur = self.env['hr.location'].search([('name', '=', 'Udaipur')], limit=1)
            self.location_ids = [(6, 0, udaipur.ids)]

        elif self.location_type == 'multiple':
            # allow manual selection
            self.location_ids = [(5, 0, 0)]


    requisition_id = fields.Char(
        string="Requisition ID",
        copy=False,
        readonly=True,
        index=True,
        default='New'
    )

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence']
        for vals in vals_list:
            if not vals.get('requisition_id') or vals.get('requisition_id') == 'New':
                vals['requisition_id'] = sequence.next_by_code(
                    'hr.job.requisition'
                ) or 'New'
        return super().create(vals_list)

    approval_state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('rm_approval', 'RM Approval'),
            ('manager_approval', 'Manager Approval'),
            ('finance_approval', 'Finance Approval'),
            ('hr_approval', 'HR Approval'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ],
        string='Approval Status',
        default='draft',
        tracking=True,
        copy=False,
    )

    rm_id = fields.Many2one(
        'hr.employee',
        string='Reporting Manager',
        tracking=True,
        copy=False,
    )

    hr_approver_id = fields.Many2one(
        'hr.employee',
        string='HR Approver',
        tracking=True,
        copy=False,
    )
    manager_approver_id = fields.Many2one(
        'hr.employee',
        string='Manager Approver',
        tracking=True,
        copy=False,
    )

    finance_approver_id = fields.Many2one(
        'hr.employee',
        string='Finance Approver',
        tracking=True,
        copy=False,
    )

    rm_approval_date = fields.Datetime(
        string='RM Approval Date',
        readonly=True,
        copy=False,
    )

    manager_approval_date = fields.Datetime(
        string='Manager Approval Date',
        readonly=True,
        copy=False,
    )

    finance_approval_date = fields.Datetime(
        string='Finance Approval Date',
        readonly=True,
        copy=False,
    )

    hr_approval_date = fields.Datetime(
        string='HR Approval Date',
        readonly=True,
        copy=False,
    )

    rejection_reason = fields.Text(
        string='Rejection Reason',
        copy=False,
    )

    def action_submit_for_approval(self):
        for job in self:
            if job.approval_state not in ('draft', 'rejected'):
                raise UserError(
                    _(
                        "Only jobs in Draft or Rejected status "
                        "can be submitted for approval."
                    )
                )
            if not job.rm_id:
                raise UserError(
                    _(
                        "Please select the Reporting Manager "
                        "before submitting the job for approval."
                    )
                )
            if not job.rm_id.user_id:
                raise UserError(
                    _(
                        "The selected Reporting Manager does not "
                        "have a related user."
                    )
                )

            if not job.manager_approver_id:
                raise UserError(
                    _(
                        "Please select the Manager Approver "
                        "before submitting the job for approval."
                    )
                )

            if not job.manager_approver_id.user_id:
                raise UserError(
                    _(
                        "The selected Manager Approver does not "
                        "have a related user."
                    )
                )

            if not job.finance_approver_id:
                raise UserError(
                    _(
                        "Please select the Finance Approver "
                        "before submitting the job for approval."
                    )
                )

            if not job.finance_approver_id.user_id:
                raise UserError(
                    _(
                        "The selected Finance Approver does not "
                        "have a related user."
                    )
                )

            if not job.hr_approver_id:
                raise UserError(
                    _(
                        "Please select the HR Approver "
                        "before submitting the job for approval."
                    )
                )

            if not job.hr_approver_id.user_id:
                raise UserError(
                    _(
                        "The selected HR Approver does not "
                        "have a related user."
                    )
                )
            job.write({
                'approval_state': 'rm_approval',
                'rejection_reason': False,
            })
            job._send_rm_approval_email()
    def action_rm_approve(self):
        current_employee = self.env['hr.employee'].search(
            [
                ('user_id', '=', self.env.user.id),
            ],
            limit=1,
        )
        for job in self:

            if job.approval_state != 'rm_approval':
                raise UserError(
                    _(
                        "This job is not waiting for RM approval."
                    )
                )

            if not job.rm_id:
                raise UserError(
                    _("Reporting Manager is not configured.")
                )

            if job.rm_id != current_employee:
                raise UserError(
                    _(
                        "Only the assigned Reporting Manager "
                        "can approve this job."
                    )
                )

            job.write({
                'approval_state': 'manager_approval',
                'rm_approval_date': fields.Datetime.now(),
            })

            job._send_manager_approval_email()

    def action_manager_approve(self):
        current_employee = self.env['hr.employee'].search(
            [('user_id', '=', self.env.user.id)],
            limit=1,
        )

        for job in self:
            if job.approval_state != 'manager_approval':
                raise UserError(_("This job is not waiting for Manager approval."))

            if not job.manager_approver_id:
                raise UserError(_("Manager Approver is not configured."))

            if job.manager_approver_id != current_employee:
                raise UserError(
                    _("Only the assigned Manager Approver can approve this job.")
                )

            job.write({
                'approval_state': 'finance_approval',
                'manager_approval_date': fields.Datetime.now(),
            })

            job._send_finance_approval_email()

    def action_finance_approve(self):
        current_employee = self.env['hr.employee'].search(
            [('user_id', '=', self.env.user.id)],
            limit=1,
        )

        for job in self:
            if job.approval_state != 'finance_approval':
                raise UserError(_("This job is not waiting for Finance approval."))

            if not job.finance_approver_id:
                raise UserError(_("Finance Approver is not configured."))

            if job.finance_approver_id != current_employee:
                raise UserError(
                    _("Only the assigned Finance Approver can approve this job.")
                )

            job.write({
                'approval_state': 'hr_approval',
                'finance_approval_date': fields.Datetime.now(),
            })

            job._send_hr_approval_email()

    def action_hr_approve(self):
        current_employee = self.env['hr.employee'].search(
            [('user_id', '=', self.env.user.id)],
            limit=1,
        )

        for job in self:
            if job.approval_state != 'hr_approval':
                raise UserError(_("This job is not waiting for HR approval."))

            if not job.hr_approver_id:
                raise UserError(_("HR Approver is not configured."))

            if job.hr_approver_id != current_employee:
                raise UserError(
                    _("Only the assigned HR Approver can approve this job.")
                )

            job.write({
                'approval_state': 'approved',
                'hr_approval_date': fields.Datetime.now(),
            })

    def action_reject(self):
        for job in self:

            if job.approval_state not in (
                'rm_approval',
                'manager_approval',
                'finance_approval',
                'hr_approval',
            ):
                raise UserError(
                    _(
                        "Only jobs waiting for approval "
                        "can be rejected."
                    )
                )

            job.write({
                'approval_state': 'rejected',
            })

    def _send_rm_approval_email(self):
        self.ensure_one()

        if not self.rm_id or not self.rm_id.work_email:
            _logger.warning(
                "Cannot send RM approval email for Job %s: "
                "RM email is missing.",
                self.display_name,
            )
            return

        base_url = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url'
        )

        job_url = (
            f"{base_url}/web#"
            f"id={self.id}"
            f"&model=hr.job"
            f"&view_type=form"
        )

        subject = _(
            "Job Approval Required - %s"
        ) % self.name

        body = f"""
            <div style="font-family: Arial, sans-serif; font-size: 14px;">

                <p>Hello {self.rm_id.name},</p>

                <p>
                    A new job position has been submitted and is
                    waiting for your approval.
                </p>

                <table style="border-collapse: collapse; width: 100%;">
                    <tr>
                        <td style="padding: 8px; font-weight: bold;">
                            Job Position
                        </td>
                        <td style="padding: 8px;">
                            {self.name}
                        </td>
                    </tr>

                    <tr>
                        <td style="padding: 8px; font-weight: bold;">
                            Department
                        </td>
                        <td style="padding: 8px;">
                            {self.department_id.name or ''}
                        </td>
                    </tr>

                    <tr>
                        <td style="padding: 8px; font-weight: bold;">
                            Company
                        </td>
                        <td style="padding: 8px;">
                            {self.company_id.name or ''}
                        </td>
                    </tr>

                    <tr>
                        <td style="padding: 8px; font-weight: bold;">
                            Positions
                        </td>
                        <td style="padding: 8px;">
                            {self.expected_employees or 0}
                        </td>
                    </tr>
                </table>

                <br/>

                <p>
                    Please review the complete job details in Odoo
                    and approve or reject the request.
                </p>

                <p>
                    <a href="{job_url}"
                       style="
                           background-color: #875A7B;
                           color: white;
                           padding: 10px 18px;
                           text-decoration: none;
                           border-radius: 4px;
                           display: inline-block;
                       ">
                        Review Job Position
                    </a>
                </p>

                <p>
                    Regards,<br/>
                    Recruitment Team
                </p>

            </div>
        """

        mail_values = {
            'subject': subject,
            'body_html': body,
            'email_to': self.rm_id.work_email,
            'email_from' : 'hrsupport@bxitech.com',
            'model': 'hr.job',
            'res_id': self.id,
        }

        self.env['mail.mail'].sudo().create(mail_values).send()

    # =========================================================
    # EMAIL - MANAGER
    # =========================================================

    def _send_manager_approval_email(self):
        self.ensure_one()

        if not self.manager_approver_id or not self.manager_approver_id.work_email:
            _logger.warning(
                "Cannot send Manager approval email for Job %s: Manager email is missing.",
                self.display_name,
            )
            return

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        job_url = f"{base_url}/web#id={self.id}&model=hr.job&view_type=form"

        subject = _("Manager Approval Required - %s") % self.name
        body = f"""
            <div style="font-family: Arial, sans-serif; font-size: 14px;">
                <p>Hello {self.manager_approver_id.name},</p>
                <p>The Reporting Manager has approved the following job position.</p>
                <p>The job is now waiting for your Manager approval.</p>
                <p><b>Job Position:</b> {self.name}</p>
                <p><b>Department:</b> {self.department_id.name or ''}</p>
                <p><b>Company:</b> {self.company_id.name or ''}</p>
                <p><b>Positions:</b> {self.expected_employees or 0}</p>
                <p><a href="{job_url}">Review Job Position</a></p>
                <p>Regards,<br/>Recruitment Team</p>
            </div>
        """

        self.env['mail.mail'].sudo().create({
            'subject': subject,
            'body_html': body,
            'email_from': 'hrsupport@bxitech.com',
            'email_to': self.manager_approver_id.work_email,
            'model': 'hr.job',
            'res_id': self.id,
        }).send()

    # =========================================================
    # EMAIL - FINANCE
    # =========================================================

    def _send_finance_approval_email(self):
        self.ensure_one()

        if not self.finance_approver_id or not self.finance_approver_id.work_email:
            _logger.warning(
                "Cannot send Finance approval email for Job %s: Finance email is missing.",
                self.display_name,
            )
            return

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        job_url = f"{base_url}/web#id={self.id}&model=hr.job&view_type=form"

        subject = _("Finance Approval Required - %s") % self.name
        body = f"""
            <div style="font-family: Arial, sans-serif; font-size: 14px;">
                <p>Hello {self.finance_approver_id.name},</p>
                <p>The Manager has approved the following job position.</p>
                <p>The job is now waiting for your Finance approval.</p>
                <p><b>Job Position:</b> {self.name}</p>
                <p><b>Department:</b> {self.department_id.name or ''}</p>
                <p><b>Company:</b> {self.company_id.name or ''}</p>
                <p><b>Positions:</b> {self.expected_employees or 0}</p>
                <p><a href="{job_url}">Review Job Position</a></p>
                <p>Regards,<br/>Recruitment Team</p>
            </div>
        """

        self.env['mail.mail'].sudo().create({
            'subject': subject,
            'body_html': body,
            'email_from': 'hrsupport@bxitech.com',
            'email_to': self.finance_approver_id.work_email,
            'model': 'hr.job',
            'res_id': self.id,
        }).send()

    # =========================================================
    # EMAIL - HR
    # =========================================================

    def _send_hr_approval_email(self):
        self.ensure_one()

        if not self.hr_approver_id or not self.hr_approver_id.work_email:
            _logger.warning(
                "Cannot send HR approval email for Job %s: "
                "HR email is missing.",
                self.display_name,
            )
            return

        base_url = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url'
        )

        job_url = (
            f"{base_url}/web#"
            f"id={self.id}"
            f"&model=hr.job"
            f"&view_type=form"
        )

        subject = _(
            "HR Approval Required - %s"
        ) % self.name

        body = f"""
            <div style="font-family: Arial, sans-serif; font-size: 14px;">

                <p>Hello {self.hr_approver_id.name},</p>

                <p>
                    The Reporting Manager has approved the following
                    job position.
                </p>

                <p>
                    The job is now waiting for your HR approval.
                </p>

                <table style="border-collapse: collapse; width: 100%;">
                    <tr>
                        <td style="padding: 8px; font-weight: bold;">
                            Job Position
                        </td>
                        <td style="padding: 8px;">
                            {self.name}
                        </td>
                    </tr>

                    <tr>
                        <td style="padding: 8px; font-weight: bold;">
                            Department
                        </td>
                        <td style="padding: 8px;">
                            {self.department_id.name or ''}
                        </td>
                    </tr>

                    <tr>
                        <td style="padding: 8px; font-weight: bold;">
                            Company
                        </td>
                        <td style="padding: 8px;">
                            {self.company_id.name or ''}
                        </td>
                    </tr>

                    <tr>
                        <td style="padding: 8px; font-weight: bold;">
                            Positions
                        </td>
                        <td style="padding: 8px;">
                            {self.expected_employees or 0}
                        </td>
                    </tr>
                </table>

                <br/>

                <p>
                    Please review the complete job details in Odoo
                    and approve or reject the request.
                </p>

                <p>
                    <a href="{job_url}"
                       style="
                           background-color: #875A7B;
                           color: white;
                           padding: 10px 18px;
                           text-decoration: none;
                           border-radius: 4px;
                           display: inline-block;
                       ">
                        Review Job Position
                    </a>
                </p>

                <p>
                    Regards,<br/>
                    Recruitment Team
                </p>

            </div>
        """

        mail_values = {
            'subject': subject,
            'body_html': body,
            'email_from' : 'hrsupport@bxitech.com',
            'email_to': self.hr_approver_id.work_email,
            'model': 'hr.job',
            'res_id': self.id,
        }

        self.env['mail.mail'].sudo().create(mail_values).send()