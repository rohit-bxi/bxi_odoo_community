from odoo import api, fields, models, _
from odoo.exceptions import UserError


class TravelRequest(models.Model):
    _name = 'travel.request'
    _description = 'Travel Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default='New',
        tracking=True
    )

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        tracking=True,
        default=lambda self: self._default_employee_id(),
    )
    manager_id = fields.Many2one(
        'hr.employee',
        string='Manager',
        tracking=True
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        tracking=True
    )

    request_by = fields.Many2one(
        'hr.employee',
        string='Request By',
        default=lambda self: self._default_employee_id(),
        readonly=True,
        tracking=True
    )
    request_date = fields.Date(
        string='Request Date',
        default=fields.Date.context_today,
        tracking=True
    )

    manager_approved_by = fields.Many2one(
        'hr.employee',
        string='Manager Approved By',
        readonly=True,
        tracking=True
    )
    manager_approved_date = fields.Datetime(
        string='Manager Approved Date',
        readonly=True,
        tracking=True
    )
    hr_approved_by = fields.Many2one(
        'hr.employee',
        string='HR Approved By',
        readonly=True,
        tracking=True
    )
    hr_approved_date = fields.Datetime(
        string='HR Approved Date',
        readonly=True,
        tracking=True
    )
    finance_approved_by = fields.Many2one(
        'hr.employee',
        string='Finance Approved By',
        readonly=True,
        tracking=True
    )
    finance_approved_date = fields.Datetime(
        string='Finance Approved Date',
        readonly=True,
        tracking=True
    )

    travel_purpose = fields.Char(
        string='Travel Purpose',
        required=True,
        tracking=True
    )
    project_id = fields.Many2one(
        'project.project',
        string='Project',
        tracking=True
    )
    analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='Analytic Account',
        tracking=True
    )

    # From address
    from_address = fields.Char(string='From Address',tracking=True,)
    from_country = fields.Many2one(
        'res.country',
        string='From Country',
        tracking=True,
        required=True,
        default=lambda self: self.env.ref('base.in').id
    )

    from_state = fields.Many2one(
        'res.country.state',
        string='From State',
        domain="[('country_id', '=', from_country)]",
        tracking=True,
    )

    from_city = fields.Char(
        string='From City',
        tracking=True,
        required=True,
    )

    # To address
    to_address = fields.Char(string='To Address',tracking=True,)
    to_city = fields.Char(string='To City',tracking=True,required=True)
    to_state = fields.Many2one(
        'res.country.state',
        string='To State',
        domain="[('country_id', '=', to_country)]",
        tracking=True,
    )
    to_country = fields.Many2one(
        'res.country',
        string='To Country',
        required=True,
        default=lambda self: self.env.ref('base.in').id
    )

    departure_date = fields.Date(
        string='Request Departure Date',
        required=True,
        tracking=True
    )
    return_date = fields.Date(
        string='Request Return Date',
        tracking=True
    )

    days = fields.Float(
        string='Days',
        compute='_compute_days',
        store=True,
        tracking=True
    )

    mode_of_travel = fields.Selection(
        [
            ('flight', 'Flight'),
            ('train', 'Train'),
            ('bus', 'Bus'),
            ('car', 'Car'),
            ('ship', 'Ship'),
            ('other', 'Other'),
        ],
        string='Request Mode of Travel',
        tracking=True
    )

    contact_number = fields.Char(string='Contact Number',tracking=True)
    email = fields.Char(string='Email',tracking=True)

    other_info = fields.Text(string='Other Info',tracking=True)

    advance_required = fields.Boolean(string='Advance Required',tracking=True)
    advance_amount = fields.Float(string='Advance Amount',tracking=True)
    advance_notes = fields.Text(string='Advance Notes',tracking=True)

    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('manager_approval', 'Manager Approval'),
            ('hr_approval', 'HR Approval'),
            ('finance_approval', 'Finance Approval'),
            # ('confirm', 'Confirmed'),
            ('approve', 'Approved'),
            ('cancel', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        tracking=True
    )

    can_manager_approve = fields.Boolean(
        compute='_compute_can_manager_approve',
        string='Can Manager Approve'
    )

    expense_line_ids = fields.One2many(
        'travel.request.expense.line',
        'travel_request_id',
        string='Expense Lines',
        copy=True,
    )

    expense_line_count = fields.Integer(
        string='Expense Line Count',
        compute='_compute_expense_line_count'
    )

    total_submitted_expense = fields.Float(
        string='Total Expense Amount',
        compute='_compute_total_expense_amount',
        store=True,
        currency_field='currency_id'
    )

    @api.depends('expense_line_ids.amount')
    def _compute_total_expense_amount(self):
        for rec in self:
            rec.total_submitted_expense = sum(rec.expense_line_ids.mapped('amount'))

    @api.depends('expense_line_ids')
    def _compute_expense_line_count(self):
        for rec in self:
            rec.expense_line_count = len(rec.expense_line_ids)

    @api.depends('expense_line_ids.amount')
    def _compute_total_submitted_expense(self):
        for rec in self:
            rec.total_submitted_expense = sum(rec.expense_line_ids.mapped('amount'))

    @api.depends('employee_id')
    def _compute_can_manager_approve(self):
        current_employee = self.env['hr.employee'].search(
            [('user_id', '=', self.env.user.id)],
            limit=1
        )
        for rec in self:
            rec.can_manager_approve = bool(
                rec.employee_id
                and rec.employee_id.parent_id
                and current_employee
                and rec.employee_id.parent_id.id == current_employee.id
            )

    @api.model
    def _default_employee_id(self):
        employee = self.env['hr.employee'].search(
            [('user_id', '=', self.env.user.id)],
            limit=1
        )
        return employee.id if employee else False

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        for rec in self:
            if rec.employee_id:
                rec.manager_id = rec.employee_id.parent_id.id or False
                rec.department_id = rec.employee_id.department_id.id or False
                rec.contact_number = rec.employee_id.work_phone or rec.employee_id.mobile_phone or False
                rec.email = rec.employee_id.work_email or False

    @api.depends('departure_date', 'return_date')
    def _compute_days(self):
        for rec in self:
            rec.days = 0
            if rec.departure_date and rec.return_date:
                if rec.return_date >= rec.departure_date:
                    delta = rec.return_date - rec.departure_date
                    rec.days = delta.days + 1

    @api.constrains('departure_date', 'return_date')
    def _check_dates(self):
        for rec in self:
            if rec.departure_date and rec.return_date and rec.return_date < rec.departure_date:
                raise UserError(_('Return date cannot be earlier than departure date.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('travel.request') or 'BXI/TR/0001'
        return super().create(vals_list)

    def action_confirm(self):
        for rec in self:
            rec.write({
                'state': 'manager_approval',
            })

    def manager_action_approve(self):
        for rec in self:
            rec.write({
                'state': 'hr_approval',
                'manager_approved_by': self.env.user.employee_id.id,
                'manager_approved_date': fields.Datetime.now(),
            })

    def hr_action_approve(self):
        for rec in self:
            rec.write({
                'state': 'finance_approval',
                'hr_approved_by': self.env.user.employee_id.id,
                'hr_approved_date': fields.Datetime.now(),
            })

    def finance_action_approve(self):
        for rec in self:
            rec.write({
                'state': 'approve',
                'finance_approved_by': self.env.user.employee_id.id,
                'finance_approved_date': fields.Datetime.now(),
            })

    def action_cancel(self):
        self.write({'state': 'cancel'})


    def action_reset_to_draft(self):
        if not self.env.user.has_group('base.group_system'):
            raise UserError("Only HR Admin can reset the request to draft.")

        self.write({
            'state': 'draft',
            'manager_approved_by': False,
            'manager_approved_date': False,
            'hr_approved_by': False,
            'hr_approved_date': False,
            'finance_approved_by': False,
            'finance_approved_date': False,
        })

    def write(self, vals):
        res = super().write(vals)
        if 'state' in vals:
            for record in self:
                record._send_state_email()
        return res
    
    def _send_state_email(self):
        self.ensure_one()
        template = False
        email_to = False
        if self.state == 'manager_approval':
            template = self.env.ref('bxi_travel_request.email_template_manager')
            email_to = self.employee_id.parent_id.work_email if self.employee_id.parent_id else False
        elif self.state == 'hr_approval':
            template = self.env.ref('bxi_travel_request.email_template_hr')
            email_to = 'hr@bxitech.com'
        elif self.state == 'finance_approval':
            template = self.env.ref('bxi_travel_request.email_template_finance')
            email_to = 'fso@bxiventure.com'
        if not template or not email_to:
            return
        template.send_mail(
            self.id,
            email_values={'email_to': email_to},
            force_send=True
        )