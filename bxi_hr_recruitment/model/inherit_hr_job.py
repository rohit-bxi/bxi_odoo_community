from odoo import models, fields, api

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
