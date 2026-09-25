import base64
import logging

from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

PARAM_PREFIX = 'bxi_salary_advance.'
# Advances that block a new application: under approval, or disbursed and not fully recovered.
OPEN_STATES = ('submitted', 'hr_review', 'exception_review', 'approved', 'disbursed', 'fnf')
# Advances not paid out yet; cancelled when the employee starts serving notice.
NOT_DISBURSED_STATES = ('draft', 'submitted', 'hr_review', 'exception_review', 'approved')
# Advances being recovered through payroll.
RECOVERY_STATES = ('disbursed', 'fnf')
# Fields only changed by the workflow methods (which run as superuser) or by HR.
WORKFLOW_FIELDS = {
    'state', 'manager_id', 'lob_id', 'company_id', 'monthly_salary', 'amount_approved',
    'installment_count', 'vendor_partner_id', 'exception_reason', 'exception_approver_id',
    'rm_approved_by_id', 'rm_approved_date', 'hr_approved_by_id', 'hr_approved_date',
    'exception_approved_by_id', 'exception_approved_date', 'hr_deadline', 'rejection_reason',
    'submitted_date', 'disbursement_date', 'disbursement_move_id', 'disbursement_reference',
    'recovery_start', 'installment_ids', 'resignation_id', 'fnf_date', 'closed_date',
    'sign_request_id', 'undertaking_signed', 'undertaking_attachment_ids', 'rm_reminder_sent',
    'sla_escalated',
}
# Fields the employee fills in; frozen once the request is submitted.
REQUEST_FIELDS = {
    'employee_id', 'category', 'emergency_type', 'nonprocessing_reason', 'reason',
    'amount_requested', 'tenancy_months', 'request_form_ids', 'rental_agreement_ids',
}
# Category I reasons for which the minimum service is waived: a new joiner or a transferee
# cannot have 6 months of service when the delay happens.
SERVICE_EXEMPT_REASONS = ('joining', 'transfer')
HR_GROUP = 'bxi_salary_advance.group_salary_advance_hr'
HR_HEAD_GROUP = 'bxi_salary_advance.group_salary_advance_hr_head'
FINANCE_GROUP = 'bxi_salary_advance.group_salary_advance_finance'


class BxiSalaryAdvance(models.Model):
    """A salary advance under the Salary Advance Policy, from the employee's request to
    the last instalment recovered through payroll."""
    _name = 'bxi.salary.advance'
    _description = 'Salary Advance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default=lambda self: self.env._('New'),
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('submitted', 'Manager Approval'),
            ('hr_review', 'HR Review'),
            ('exception_review', 'Exception Approval'),
            ('approved', 'Approved'),
            ('disbursed', 'Recovering'),
            ('fnf', 'Full & Final Settlement'),
            ('closed', 'Closed'),
            ('rejected', 'Rejected'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status', default='draft', required=True, tracking=True, copy=False, index=True,
    )

    # ── Employee ─────────────────────────────────────────────────────────
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, tracking=True, index=True,
        default=lambda self: self.env.user.employee_id,
    )
    employee_user_id = fields.Many2one(related='employee_id.user_id', string='Employee User')
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        compute='_compute_company_id', store=True, readonly=False, precompute=True,
    )
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    department_id = fields.Many2one(related='employee_id.department_id', store=True)
    manager_id = fields.Many2one(
        'hr.employee', string='Reporting Manager', readonly=True, copy=False, tracking=True,
    )
    manager_user_id = fields.Many2one(related='manager_id.user_id', string='Reporting Manager User')
    lob_id = fields.Many2one('bxi.line.of.business', string='Line of Business', readonly=True, copy=False)

    # ── Request ──────────────────────────────────────────────────────────
    category = fields.Selection(
        [
            ('non_processing', 'I - Salary Not Processed'),
            ('emergency', 'II - Emergency'),
            ('housing', 'III - Housing Deposit / Rent'),
        ],
        string='Category', required=True, default='emergency', tracking=True,
    )
    nonprocessing_reason = fields.Selection(
        [
            ('transfer', 'Delay in transfer formalities'),
            ('joining', 'Incomplete joining formalities'),
            ('other', 'Other unavoidable circumstances'),
        ],
        string='Reason Salary Was Not Processed',
    )
    emergency_type = fields.Selection(
        [
            ('birth', 'Birth of a child'),
            ('marriage', 'Own marriage'),
            ('medical', 'Medical emergency (self or immediate family)'),
            ('bereavement', 'Bereavement (immediate family)'),
            ('other', 'Other dire emergency'),
        ],
        string='Emergency',
    )
    reason = fields.Text(string='Details')
    tenancy_months = fields.Integer(
        string='Tenancy (Months)',
        help="Duration of the rental agreement; the advance is recovered over the same number of months.",
    )
    amount_requested = fields.Monetary(string='Amount Requested', currency_field='currency_id', tracking=True)
    monthly_salary = fields.Monetary(
        string='Monthly Salary', currency_field='currency_id',
        compute='_compute_monthly_salary', store=True, readonly=False, copy=False,
        groups='bxi_salary_advance.group_salary_advance_hr,bxi_salary_advance.group_salary_advance_finance',
        help="Current monthly salary the advance limit is based on. Taken from the employee when the "
             "request is submitted; HR may correct it during the review.",
    )
    max_eligible = fields.Monetary(
        string='Maximum Eligible', currency_field='currency_id', compute='_compute_max_eligible',
        groups='bxi_salary_advance.group_salary_advance_hr,bxi_salary_advance.group_salary_advance_finance',
        help="Policy limit for this category. Empty for housing advances when no limit is configured.",
    )
    request_form_ids = fields.Many2many(
        'ir.attachment', 'bxi_salary_advance_request_form_rel', 'advance_id', 'attachment_id',
        string='Signed Request Form',
        help="Completed and signed Advance Request Form.",
    )
    rental_agreement_ids = fields.Many2many(
        'ir.attachment', 'bxi_salary_advance_rental_rel', 'advance_id', 'attachment_id',
        string='Rental Agreement / LOI',
    )

    # ── Approval ─────────────────────────────────────────────────────────
    amount_approved = fields.Monetary(string='Amount Approved', currency_field='currency_id', tracking=True, copy=False)
    installment_count = fields.Integer(
        string='Number of EMIs', compute='_compute_installment_count', store=True, readonly=False,
        help="Category I: recovered in full from the next payroll. Category II: equal EMIs. "
             "Category III: one EMI per month of the tenancy.",
    )
    installment_amount = fields.Monetary(
        string='Monthly EMI', currency_field='currency_id', compute='_compute_installment_amount',
    )
    vendor_partner_id = fields.Many2one(
        'res.partner', string='Third-Party Vendor', tracking=True, copy=False,
        help="Housing advances are routed through this third party after HR approval.",
    )
    submitted_date = fields.Datetime(string='Submitted On', readonly=True, copy=False)
    rm_approved_by_id = fields.Many2one('res.users', string='Manager Approved By', readonly=True, copy=False)
    rm_approved_date = fields.Datetime(string='Manager Approved On', readonly=True, copy=False)
    hr_deadline = fields.Date(
        string='HR Processing Deadline', readonly=True, copy=False, tracking=True,
        help="HR processes the request within the configured number of working days after the "
             "Reporting Manager's approval.",
    )
    hr_approved_by_id = fields.Many2one('res.users', string='HR Approved By', readonly=True, copy=False)
    hr_approved_date = fields.Datetime(string='HR Approved On', readonly=True, copy=False)
    exception_reason = fields.Text(string='Exceptions', readonly=True, copy=False)
    exception_approver_id = fields.Many2one('res.users', string='Exception Approver', readonly=True, copy=False)
    exception_approved_by_id = fields.Many2one('res.users', string='Exception Approved By', readonly=True, copy=False)
    exception_approved_date = fields.Datetime(string='Exception Approved On', readonly=True, copy=False)
    rejection_reason = fields.Text(string='Rejection Reason', readonly=True, copy=False)
    rm_reminder_sent = fields.Boolean(copy=False)
    sla_escalated = fields.Boolean(string='Escalated', copy=False)
    is_overdue = fields.Boolean(string='Overdue', compute='_compute_is_overdue', search='_search_is_overdue')

    # ── Housing undertaking ──────────────────────────────────────────────
    sign_request_id = fields.Many2one('sign.request', string='Undertaking Signature', readonly=True, copy=False)
    undertaking_signed = fields.Boolean(string='Undertaking Signed', copy=False, tracking=True)
    undertaking_attachment_ids = fields.Many2many(
        'ir.attachment', 'bxi_salary_advance_undertaking_rel', 'advance_id', 'attachment_id',
        string='Signed Undertaking (Paper)', copy=False,
        help="Scanned loan undertaking when it was signed on paper instead of electronically.",
    )

    # ── Disbursement and recovery ────────────────────────────────────────
    disbursement_date = fields.Date(string='Disbursed On', readonly=True, copy=False, tracking=True)
    disbursement_reference = fields.Char(string='Payment Reference', readonly=True, copy=False)
    disbursement_move_id = fields.Many2one('account.move', string='Disbursement Entry', readonly=True, copy=False)
    recovery_start = fields.Date(string='Recovery Starts', readonly=True, copy=False)
    installment_ids = fields.One2many('bxi.salary.advance.installment', 'advance_id', string='EMI Schedule', copy=False)
    amount_disbursed = fields.Monetary(
        string='Amount Disbursed', currency_field='currency_id', compute='_compute_amounts', store=True)
    amount_recovered = fields.Monetary(
        string='Amount Recovered', currency_field='currency_id', compute='_compute_amounts', store=True)
    amount_balance = fields.Monetary(
        string='Outstanding Balance', currency_field='currency_id', compute='_compute_amounts', store=True)
    resignation_id = fields.Many2one('employee.resignation', string='Resignation', readonly=True, copy=False)
    fnf_date = fields.Date(string='Settled in F&F On', readonly=True, copy=False)
    closed_date = fields.Date(string='Closed On', readonly=True, copy=False)
    is_perquisite = fields.Boolean(
        string='Possible Taxable Perquisite', compute='_compute_is_perquisite',
        help="Interest-free advances whose outstanding total exceeds the configured threshold may be a "
             "taxable perquisite in India (Rule 3(7)(i)); inform the payroll team for TDS.",
    )

    # ── Access helpers ───────────────────────────────────────────────────
    can_rm_approve = fields.Boolean(compute='_compute_can_act')
    can_hr_process = fields.Boolean(compute='_compute_can_act')
    can_exception_approve = fields.Boolean(compute='_compute_can_act')
    can_disburse = fields.Boolean(compute='_compute_can_act')

    _amount_requested_positive = models.Constraint(
        'CHECK(amount_requested >= 0)', 'The requested amount cannot be negative.',
    )

    # ── Computes ─────────────────────────────────────────────────────────
    @api.depends('employee_id')
    def _compute_company_id(self):
        for rec in self:
            rec.company_id = rec.employee_id.sudo().company_id or rec.company_id or self.env.company

    @api.depends('employee_id')
    def _compute_monthly_salary(self):
        for rec in self:
            if rec.state == 'draft':
                rec.monthly_salary = rec.employee_id.sudo()._sa_get_monthly_salary()
            else:
                rec.monthly_salary = rec.monthly_salary

    @api.depends('monthly_salary', 'category')
    def _compute_max_eligible(self):
        limit = self._get_param('limit_percent', 75)
        housing_limit = self._get_param('housing_limit_percent', 0)
        for rec in self:
            percent = housing_limit if rec.category == 'housing' else limit
            rec.max_eligible = rec.currency_id.round(rec.monthly_salary * percent / 100) if percent else 0.0

    @api.depends('category', 'tenancy_months')
    def _compute_installment_count(self):
        emergency = int(self._get_param('emergency_installments', 3))
        for rec in self:
            if rec.category == 'non_processing':
                rec.installment_count = 1
            elif rec.category == 'emergency':
                rec.installment_count = emergency
            else:
                rec.installment_count = rec.tenancy_months

    @api.depends('amount_approved', 'amount_requested', 'installment_count')
    def _compute_installment_amount(self):
        for rec in self:
            amount = rec.amount_approved or rec.amount_requested
            rec.installment_amount = rec.currency_id.round(amount / rec.installment_count) \
                if rec.installment_count > 0 else 0.0

    @api.depends('state', 'amount_approved', 'disbursement_date', 'installment_ids.amount_recovered')
    def _compute_amounts(self):
        for rec in self:
            rec.amount_disbursed = rec.amount_approved if rec.disbursement_date else 0.0
            rec.amount_recovered = sum(rec.installment_ids.mapped('amount_recovered'))
            rec.amount_balance = rec.currency_id.round(rec.amount_disbursed - rec.amount_recovered)

    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_overdue = bool(
                rec.hr_deadline and rec.hr_deadline < today
                and rec.state in ('hr_review', 'exception_review', 'approved'))

    def _search_is_overdue(self, operator, value):
        if operator not in ('in', 'not in'):
            return NotImplemented
        domain = [
            ('hr_deadline', '<', fields.Date.context_today(self)),
            ('state', 'in', ('hr_review', 'exception_review', 'approved')),
        ]
        return domain if operator == 'in' else ['!', *domain]

    @api.depends('employee_id', 'amount_approved', 'amount_requested', 'category', 'emergency_type')
    def _compute_is_perquisite(self):
        threshold = self._get_param('perquisite_threshold', 20000)
        for rec in self:
            if not threshold or rec.company_id.country_id.code != 'IN':
                rec.is_perquisite = False
                continue
            others = self.sudo().search([
                ('employee_id', '=', rec.employee_id.id),
                ('state', 'in', RECOVERY_STATES),
                ('id', 'not in', rec._origin.ids),
            ])
            own = rec.amount_balance if rec.state in RECOVERY_STATES else (rec.amount_approved or rec.amount_requested)
            if rec.state in ('closed', 'rejected', 'cancelled'):
                own = 0.0
            rec.is_perquisite = bool(own) and own + sum(others.mapped('amount_balance')) > threshold

    @api.depends_context('uid')
    @api.depends('state', 'manager_id', 'exception_approver_id')
    def _compute_can_act(self):
        user = self.env.user
        is_hr = user.has_group(HR_GROUP)
        is_hr_head = user.has_group(HR_HEAD_GROUP)
        is_finance = user.has_group(FINANCE_GROUP)
        for rec in self:
            is_rm = rec.sudo().manager_id.user_id == user and rec.sudo().employee_id.user_id != user
            rec.can_rm_approve = rec.state == 'submitted' and (is_rm or is_hr)
            rec.can_hr_process = rec.state == 'hr_review' and is_hr
            rec.can_exception_approve = rec.state == 'exception_review' and (
                is_hr_head or rec.exception_approver_id == user)
            rec.can_disburse = rec.state == 'approved' and is_finance

    # ── Constraints ──────────────────────────────────────────────────────
    @api.constrains('amount_approved', 'amount_requested')
    def _check_amount_approved(self):
        for rec in self:
            if rec.amount_approved < 0:
                raise ValidationError(self.env._("The approved amount cannot be negative."))
            if rec.amount_approved and rec.currency_id.compare_amounts(rec.amount_approved, rec.amount_requested) > 0:
                raise ValidationError(self.env._("The approved amount cannot exceed the amount requested."))

    # ── CRUD ─────────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', self.env._('New')) == self.env._('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.salary.advance') or self.env._('New')
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and not self.env.user.has_group(HR_GROUP):
            protected = WORKFLOW_FIELDS & vals.keys()
            if protected:
                raise AccessError(self.env._("These fields are set by the approval workflow: %(fields)s",
                                             fields=', '.join(sorted(protected))))
            if REQUEST_FIELDS & vals.keys() and any(rec.state != 'draft' for rec in self):
                raise UserError(self.env._("The request has been submitted and can no longer be modified."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(rec.state not in ('draft', 'cancelled') for rec in self):
            raise UserError(self.env._("Only draft or cancelled salary advances can be deleted."))

    # ── Helpers ──────────────────────────────────────────────────────────
    @api.model
    def _get_param(self, key, default):
        value = self.env['ir.config_parameter'].sudo().get_param(PARAM_PREFIX + key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @api.model
    def _get_bool_param(self, key):
        value = self.env['ir.config_parameter'].sudo().get_param(PARAM_PREFIX + key, False)
        return str(value).strip().lower() not in ('', '0', 'false', 'none')

    @api.model
    def _get_str_param(self, key, default):
        return self.env['ir.config_parameter'].sudo().get_param(PARAM_PREFIX + key, default) or default

    @api.model
    def _get_housing_tenancies(self):
        value = self.env['ir.config_parameter'].sudo().get_param(PARAM_PREFIX + 'housing_tenancies', '6,12')
        return sorted({int(part) for part in (value or '').split(',') if part.strip().isdigit()})

    def _category_label(self):
        self.ensure_one()
        return dict(self._fields['category']._description_selection(self.env)).get(self.category)

    def _notify_user(self, user, summary, note=''):
        """Create a to-do activity for a user (which also emails them)."""
        self.ensure_one()
        if user:
            self.sudo().activity_schedule(
                'mail.mail_activity_data_todo', user_id=user.id, summary=summary, note=note)

    def _notify_group(self, responsible, group_xmlid, summary, note=''):
        """Notify the company's responsible user, or every member of the group in the company."""
        self.ensure_one()
        users = responsible
        if not users:
            users = self.env.ref(group_xmlid).sudo().all_user_ids.filtered(
                lambda user: self.company_id in user.company_ids and not user.share)
        for user in users:
            self._notify_user(user, summary, note)

    def _notify_employee(self, body):
        self.ensure_one()
        employee = self.employee_id.sudo()
        partner = employee.work_contact_id or employee.user_id.partner_id
        self.sudo().message_post(body=body, partner_ids=partner.ids, subtype_xmlid='mail.mt_comment')

    def _close_activities(self, feedback=False):
        self.sudo().activity_ids.filtered(lambda act: act.user_id == self.env.user).action_feedback(feedback=feedback)

    def _get_hr_deadline(self, start):
        self.ensure_one()
        days = int(self._get_param('hr_sla_days', 7))
        employee = self.employee_id.sudo()
        calendar = self.company_id.resource_calendar_id or employee.resource_calendar_id
        if calendar and days:
            deadline = calendar.plan_days(days, start)
            if deadline:
                return deadline.date()
        return fields.Date.add(start.date(), days=days)

    # ── Eligibility ──────────────────────────────────────────────────────
    def _get_eligibility_issues(self, check_documents=True):
        """Return the reasons, as sentences, why this request breaks the Salary Advance Policy.

        Works on new (unsaved) records as well, so the portal can warn before submitting."""
        self.ensure_one()
        rec = self.sudo()
        employee = rec.employee_id
        issues = []
        if not employee:
            return [self.env._("Select the employee.")]
        today = fields.Date.context_today(self)

        if not employee._sa_is_eligible_type():
            issues.append(self.env._("Salary advances are available to full-time employees only."))

        if employee._sa_is_serving_notice():
            issues.append(self.env._("Employees serving their notice period are not eligible for a salary advance."))

        min_months = int(self._get_param('min_service_months', 6))
        needs_service = rec.category == 'emergency' or (
            rec.category == 'non_processing' and (
                rec.nonprocessing_reason not in SERVICE_EXEMPT_REASONS
                or self._get_bool_param('nonprocessing_require_service')))
        if needs_service and min_months:
            start = employee._sa_get_service_start()
            if not start or start + relativedelta(months=min_months) > today:
                issues.append(self.env._(
                    "A minimum of %(months)s months of continuous service is required.", months=min_months))

        if rec.category == 'non_processing' and rec.company_id.country_id.code != 'IN':
            issues.append(self.env._("Category I advances apply only to employees in India."))

        if rec.category == 'non_processing':
            paid = employee._sa_salary_processed_in_last_payroll()
            if paid:
                issues.append(self.env._(
                    "Your salary was processed in the last payroll (%(period)s); Category I applies only "
                    "when the last payroll did not pay you.",
                    period=paid.date_to.strftime('%B %Y')))

        outstanding = False
        if self._get_str_param('outstanding_scope', 'all') == 'all' or rec.category == 'emergency':
            outstanding = self.sudo().search([
                ('employee_id', '=', employee.id),
                ('state', 'in', OPEN_STATES),
                ('id', 'not in', rec._origin.ids),
            ], limit=1)
        if outstanding:
            issues.append(self.env._(
                "Another advance (%(name)s) is still open or not fully recovered.", name=outstanding.name))

        if rec.category == 'non_processing' and not rec.nonprocessing_reason:
            issues.append(self.env._("Select why your salary was not processed."))
        if rec.category == 'emergency' and not rec.emergency_type:
            issues.append(self.env._("Select the type of emergency."))
        if rec.category == 'housing' and rec.tenancy_months <= 0:
            issues.append(self.env._("Enter the tenancy duration of the rental agreement."))

        if rec.currency_id.compare_amounts(rec.amount_requested, 0) <= 0:
            issues.append(self.env._("Enter the amount requested."))
        elif rec.category in ('non_processing', 'emergency'):
            if rec.monthly_salary <= 0:
                issues.append(self.env._("Your monthly salary is not configured. Please contact HR."))
            elif rec.currency_id.compare_amounts(rec.amount_requested, rec.max_eligible) > 0:
                issues.append(self.env._(
                    "The amount requested exceeds the limit of %(percent)s%% of the monthly salary (%(max)s).",
                    percent=int(self._get_param('limit_percent', 75)),
                    max=rec.currency_id.format(rec.max_eligible)))

        if check_documents:
            if not rec.request_form_ids and not self._get_bool_param('request_form_optional'):
                issues.append(self.env._("Upload the completed and signed Advance Request Form."))
            if rec.category == 'housing' and not rec.rental_agreement_ids:
                issues.append(self.env._("Upload the rental agreement or the Letter of Intent."))
            if employee._sa_get_policy_status()['required']:
                issues.append(self.env._("Read and acknowledge the Salary Advance Policy before applying."))
        return issues

    def _check_eligibility(self, check_documents=True):
        for rec in self:
            issues = rec._get_eligibility_issues(check_documents=check_documents)
            if issues:
                raise UserError('\n'.join(issues))

    def _get_exceptions(self):
        """Deviations from the policy that the LoB HR Head or Geo HR Head must approve."""
        self.ensure_one()
        rec = self.sudo()
        exceptions = []
        if rec.category == 'housing':
            tenancies = self._get_housing_tenancies()
            if tenancies and rec.installment_count not in tenancies:
                exceptions.append(self.env._(
                    "Recovery over %(count)s months instead of the standard %(standard)s months.",
                    count=rec.installment_count, standard='/'.join(str(t) for t in tenancies)))
            if rec.max_eligible and rec.currency_id.compare_amounts(rec.amount_approved, rec.max_eligible) > 0:
                exceptions.append(self.env._(
                    "The amount exceeds the housing limit of %(max)s.", max=rec.currency_id.format(rec.max_eligible)))
        elif rec.category == 'emergency':
            standard = int(self._get_param('emergency_installments', 3))
            if rec.installment_count != standard:
                exceptions.append(self.env._(
                    "Recovery in %(count)s EMIs instead of the standard %(standard)s.",
                    count=rec.installment_count, standard=standard))
        return exceptions

    def _get_exception_approver(self):
        self.ensure_one()
        employee = self.employee_id.sudo()
        if employee.onsite_offshore == 'onsite':
            user = self.company_id.sa_geo_hr_head_id
            role = self.env._("Geo HR Head")
        else:
            user = self.lob_id.sudo().hr_head_id.user_id
            role = self.env._("LoB HR Head")
        if not user:
            raise UserError(self.env._(
                "This request needs the approval of the %(role)s, but none is configured for %(employee)s. "
                "Set it on the Line of Business or in the Salary Advance settings.",
                role=role, employee=employee.name))
        return user

    # ── Workflow ─────────────────────────────────────────────────────────
    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(self.env._("Only draft requests can be submitted."))
            employee = rec.employee_id.sudo()
            rec.sudo().monthly_salary = employee._sa_get_monthly_salary()
            rec._check_eligibility()
            if not employee.parent_id.user_id:
                raise UserError(self.env._(
                    "%(employee)s has no Reporting Manager with a user account.", employee=employee.name))
            rec.sudo().write({
                'state': 'submitted',
                'manager_id': employee.parent_id.id,
                'lob_id': employee.lob_id.id,
                'company_id': employee.company_id.id,
                'submitted_date': fields.Datetime.now(),
                'rm_reminder_sent': False,
            })
            rec._notify_user(
                employee.parent_id.user_id,
                self.env._("Salary advance approval: %(employee)s", employee=employee.name),
                self.env._("%(category)s - %(amount)s", category=rec._category_label(),
                           amount=rec.currency_id.format(rec.amount_requested)),
            )

    def action_rm_approve(self):
        for rec in self:
            if not rec.can_rm_approve:
                raise UserError(self.env._("You are not allowed to approve this request."))
            now = fields.Datetime.now()
            rec.sudo().write({
                'state': 'hr_review',
                'rm_approved_by_id': self.env.user.id,
                'rm_approved_date': now,
                'hr_deadline': rec._get_hr_deadline(now),
                'sla_escalated': False,
            })
            rec._close_activities(self.env._("Approved"))
            rec._notify_group(
                rec.company_id.sa_hr_user_id, HR_GROUP,
                self.env._("Process salary advance: %(employee)s", employee=rec.sudo().employee_id.name),
                self.env._("Approved by the Reporting Manager. Process by %(date)s.", date=rec.hr_deadline),
            )
            rec._notify_employee(self.env._(
                "Your Reporting Manager approved salary advance %(name)s. HR will process it by %(date)s.",
                name=rec.name, date=rec.hr_deadline))

    def action_hr_approve(self):
        for rec in self:
            if not rec.can_hr_process:
                raise UserError(self.env._("Only HR can process this request."))
            sudo_rec = rec.sudo()
            if not sudo_rec.amount_approved:
                sudo_rec.amount_approved = sudo_rec.amount_requested
            if sudo_rec.installment_count <= 0:
                raise UserError(self.env._("Enter the number of EMIs."))
            if rec.category == 'non_processing' and sudo_rec.installment_count != 1:
                raise UserError(self.env._(
                    "Category I advances are recovered in full from the next payroll; no exceptions are allowed."))
            rec._check_eligibility()
            if rec.category == 'housing' and not rec.vendor_partner_id:
                raise UserError(self.env._("Select the third-party vendor the housing advance is routed through."))
            sudo_rec.write({'hr_approved_by_id': self.env.user.id, 'hr_approved_date': fields.Datetime.now()})
            rec._close_activities(self.env._("Approved"))
            exceptions = rec._get_exceptions()
            if exceptions:
                approver = rec._get_exception_approver()
                sudo_rec.write({
                    'state': 'exception_review',
                    'exception_reason': '\n'.join(exceptions),
                    'exception_approver_id': approver.id,
                })
                rec._notify_user(
                    approver,
                    self.env._("Salary advance exception: %(employee)s", employee=sudo_rec.employee_id.name),
                    '<br/>'.join(exceptions),
                )
            else:
                rec._action_approve()

    def action_exception_approve(self):
        for rec in self:
            if not rec.can_exception_approve:
                raise UserError(self.env._("You are not allowed to approve this exception."))
            rec.sudo().write({
                'exception_approved_by_id': self.env.user.id,
                'exception_approved_date': fields.Datetime.now(),
            })
            rec._close_activities(self.env._("Exception approved"))
            rec._action_approve()

    def _action_approve(self):
        for rec in self:
            rec.sudo().state = 'approved'
            if rec.category == 'housing' and not rec.undertaking_signed:
                rec._try_send_undertaking()
            rec._notify_group(
                rec.company_id.sa_finance_user_id, FINANCE_GROUP,
                self.env._("Disburse salary advance: %(employee)s", employee=rec.sudo().employee_id.name),
                self.env._("%(amount)s approved.", amount=rec.currency_id.format(rec.amount_approved)),
            )
            rec._notify_employee(self.env._(
                "Salary advance %(name)s has been approved for %(amount)s, recovered in %(count)s EMI(s).",
                name=rec.name, amount=rec.currency_id.format(rec.amount_approved), count=rec.installment_count))

    def _check_can_reject(self):
        for rec in self:
            allowed = rec.can_rm_approve or rec.can_hr_process or rec.can_exception_approve or (
                rec.state == 'approved' and self.env.user.has_group(HR_GROUP))
            if not allowed:
                raise UserError(self.env._("You are not allowed to reject this request."))

    def _action_reject(self, reason):
        for rec in self:
            rec.sudo().write({'state': 'rejected', 'rejection_reason': reason})
            rec.sudo().activity_unlink(['mail.mail_activity_data_todo'])
            rec._notify_employee(self.env._(
                "Salary advance %(name)s was rejected by %(user)s. Reason: %(reason)s",
                name=rec.name, user=self.env.user.name, reason=reason))

    def action_open_reject_wizard(self):
        self.ensure_one()
        self._check_can_reject()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Reject Salary Advance'),
            'res_model': 'bxi.salary.advance.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_advance_id': self.id},
        }

    def action_cancel(self):
        for rec in self:
            if rec.state not in ('draft', 'submitted'):
                raise UserError(self.env._("Only requests not yet reviewed by HR can be cancelled."))
            rec.sudo().state = 'cancelled'
            rec.sudo().activity_unlink(['mail.mail_activity_data_todo'])

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ('rejected', 'cancelled'):
                raise UserError(self.env._("Only rejected or cancelled requests can be reset to draft."))
            rec.sudo().write({
                'state': 'draft', 'rejection_reason': False, 'exception_reason': False,
                'exception_approver_id': False, 'amount_approved': 0.0, 'hr_deadline': False,
            })

    def _cancel_for_resignation(self, resignation):
        """Employees serving notice are not eligible: drop advances not paid out yet."""
        for rec in self.filtered(lambda r: r.state in NOT_DISBURSED_STATES):
            rec.sudo().write({'state': 'cancelled', 'resignation_id': resignation.id})
            rec.sudo().activity_unlink(['mail.mail_activity_data_todo'])
            if rec.sudo().sign_request_id.state == 'sent':
                rec.sudo().sign_request_id.cancel()
            rec._notify_employee(self.env._(
                "Salary advance %(name)s was cancelled because a resignation was submitted: employees "
                "serving their notice period are not eligible.", name=rec.name))

    # ── Housing undertaking ──────────────────────────────────────────────
    def _get_signer_partner(self):
        self.ensure_one()
        employee = self.employee_id.sudo()
        partner = employee.work_contact_id or employee.user_id.partner_id
        if not partner or not partner.email:
            raise UserError(self.env._("%(employee)s has no work email to receive the undertaking.",
                                       employee=employee.name))
        return partner

    def action_send_undertaking(self):
        for rec in self:
            if rec.category != 'housing' or rec.state != 'approved':
                raise UserError(self.env._("The loan undertaking is only sent for approved housing advances."))
            partner = rec._get_signer_partner()
            report = self.env.ref('bxi_salary_advance.action_report_loan_undertaking')
            pdf, report_type = self.env['ir.actions.report'].sudo()._render_qweb_pdf(report, rec.ids)
            if report_type != 'pdf':
                raise UserError(self.env._("The loan undertaking could not be rendered as a PDF."))
            SignTemplate = self.env['sign.template'].sudo()
            template_info = SignTemplate.create_from_attachment_data([{
                'name': f"{rec.name} - Loan Undertaking.pdf",
                'datas': base64.b64encode(pdf),
            }], active=False)
            template = SignTemplate.browse(template_info['id'])
            document = template.document_ids[:1]
            role = self.env.ref('sign.sign_item_role_default')
            last_page = max(document.num_pages, 1)
            self.env['sign.item'].sudo().create([
                {
                    'document_id': document.id,
                    'type_id': self.env.ref('sign.sign_item_type_signature').id,
                    'responsible_id': role.id,
                    'page': last_page,
                    'posX': 0.08, 'posY': 0.78, 'width': 0.30, 'height': 0.06,
                },
                {
                    'document_id': document.id,
                    'type_id': self.env.ref('sign.sign_item_type_date').id,
                    'responsible_id': role.id,
                    'page': last_page,
                    'posX': 0.60, 'posY': 0.80, 'width': 0.20, 'height': 0.03,
                },
            ])
            old_request = rec.sudo().sign_request_id
            if old_request.state == 'sent':
                old_request.cancel()
            sign_request = self.env['sign.request'].sudo().create({
                'template_id': template.id,
                'reference': self.env._("Loan Undertaking %(name)s", name=rec.name),
                'reference_doc': f"{rec._name},{rec.id}",
                'subject': self.env._("Salary advance loan undertaking to sign"),
                'request_item_ids': [Command.create({'partner_id': partner.id, 'role_id': role.id})],
            })
            rec.sudo().sign_request_id = sign_request

    def _try_send_undertaking(self):
        """Send the undertaking without blocking the approval if it fails."""
        for rec in self:
            try:
                with self.env.cr.savepoint():
                    rec.action_send_undertaking()
            except Exception as error:  # noqa: BLE001 - HR can send it again or record a paper copy
                message = str(error)
                _logger.warning("Could not send the loan undertaking of %s for signature: %s", rec.name, message)
                rec.sudo().message_post(body=self.env._(
                    "The loan undertaking could not be sent for signature automatically (%(error)s). "
                    "Please send it again or attach a signed paper copy.", error=message))
                rec._notify_group(
                    rec.company_id.sa_hr_user_id, HR_GROUP,
                    self.env._("Loan undertaking not sent: %(name)s", name=rec.name), message)

    def _on_undertaking_signed(self):
        for rec in self:
            rec.undertaking_signed = True
            rec.message_post(body=self.env._("The loan undertaking has been signed."))

    def _get_portal_sign_url(self):
        self.ensure_one()
        sign_request = self.sudo().sign_request_id
        item = sign_request.request_item_ids[:1]
        if self.undertaking_signed or not item or sign_request.state != 'sent':
            return False
        return f'/sign/document/{sign_request.id}/{item.access_token}?portal=1'

    # ── Disbursement ─────────────────────────────────────────────────────
    def action_open_disburse_wizard(self):
        self.ensure_one()
        if not self.can_disburse:
            raise UserError(self.env._("Only Finance can disburse approved advances."))
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Disburse Salary Advance'),
            'res_model': 'bxi.salary.advance.disburse.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_advance_id': self.id},
        }

    def _get_employee_partner(self):
        self.ensure_one()
        employee = self.employee_id.sudo()
        partner = employee.work_contact_id or employee.user_id.partner_id
        if not partner:
            raise UserError(self.env._("%(employee)s has no contact to post the advance on.", employee=employee.name))
        return partner

    def _prepare_disbursement_move(self, journal, date, reference):
        self.ensure_one()
        company = self.company_id
        advance_account = company.sa_advance_account_id
        if not advance_account:
            raise UserError(self.env._("Set the Employee Advance Account in the Salary Advance settings."))
        if self.category == 'housing':
            vendor = self.vendor_partner_id
            credit_account = vendor.with_company(company).property_account_payable_id
            credit_partner = vendor
        else:
            credit_account = journal.outbound_payment_method_line_ids.payment_account_id[:1] \
                or journal.default_account_id
            credit_partner = self._get_employee_partner()
        if not credit_account:
            raise UserError(self.env._("No account to credit the disbursement on was found on %(journal)s.",
                                       journal=journal.display_name))
        label = self.env._("Salary advance %(name)s - %(employee)s", name=self.name, employee=self.employee_id.name)
        amount = self.amount_approved
        return {
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': date,
            'ref': reference or self.name,
            'company_id': company.id,
            'line_ids': [
                Command.create({
                    'name': label, 'account_id': advance_account.id,
                    'partner_id': self._get_employee_partner().id, 'debit': amount, 'credit': 0.0,
                }),
                Command.create({
                    'name': label, 'account_id': credit_account.id,
                    'partner_id': credit_partner.id, 'debit': 0.0, 'credit': amount,
                }),
            ],
        }

    def _action_disburse(self, date, reference=False, journal=False):
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(self.env._("Only approved advances can be disbursed."))
        if self.category == 'housing' and not self.undertaking_signed:
            raise UserError(self.env._(
                "The employee must sign the loan undertaking before the housing advance is disbursed."))
        rec = self.sudo()
        vals = {
            'state': 'disbursed',
            'disbursement_date': date,
            'disbursement_reference': reference,
            'recovery_start': self._get_recovery_start(date),
        }
        if journal:
            # Finance users of the policy need no accounting rights to book the advance.
            move = self.env['account.move'].sudo().create(
                rec._prepare_disbursement_move(journal.sudo(), date, reference))
            move.action_post()
            vals['disbursement_move_id'] = move.id
        rec.write(vals)
        rec._generate_installments()
        rec.activity_unlink(['mail.mail_activity_data_todo'])
        first = rec.installment_ids.sorted('due_date')[:1]
        self._notify_employee(self.env._(
            "Salary advance %(name)s of %(amount)s has been disbursed. Recovery of %(count)s EMI(s) of "
            "%(emi)s starts with the payroll of %(month)s.",
            name=rec.name, amount=rec.currency_id.format(rec.amount_approved), count=len(rec.installment_ids),
            emi=rec.currency_id.format(first.amount), month=first.due_date.strftime('%B %Y')))

    def _get_recovery_start(self, disbursed_on):
        """Category I is recovered in full by the next payroll, which also pays the arrears: the
        first month from the disbursement on whose payroll is not confirmed yet. The other
        categories are recovered from the month following the disbursement."""
        self.ensure_one()
        if self.category == 'non_processing':
            return self.employee_id.sudo()._sa_first_open_payroll_month(disbursed_on)
        return disbursed_on + relativedelta(months=1, day=1)

    def _generate_installments(self):
        self.ensure_one()
        count = max(self.installment_count, 1)
        currency = self.currency_id
        emi = currency.round(self.amount_approved / count)
        commands = [Command.unlink(inst.id) for inst in self.installment_ids if inst.state == 'pending']
        for index in range(count):
            # The last EMI absorbs the rounding difference.
            amount = emi if index < count - 1 else currency.round(self.amount_approved - emi * (count - 1))
            commands.append(Command.create({
                'sequence': index + 1,
                'due_date': self.recovery_start + relativedelta(months=index),
                'amount': amount,
            }))
        self.installment_ids = commands

    # ── Full & Final Settlement ──────────────────────────────────────────
    def _move_to_fnf(self, last_day, resignation=False, note=False):
        """Recover the whole outstanding balance with the payroll of the last working month."""
        for rec in self.sudo().filtered(lambda r: r.state == 'disbursed'):
            pending = rec.installment_ids.filtered(lambda inst: inst.state == 'pending')
            balance = rec.currency_id.round(sum(pending.mapped('amount')))
            pending.unlink()
            vals = {'state': 'fnf', 'fnf_date': last_day}
            if resignation:
                vals['resignation_id'] = resignation.id
            if rec.currency_id.compare_amounts(balance, 0) > 0:
                vals['installment_ids'] = [Command.create({
                    'sequence': max(rec.installment_ids.mapped('sequence') or [0]) + 1,
                    'due_date': last_day.replace(day=1),
                    'amount': balance,
                    'is_fnf': True,
                })]
            rec.write(vals)
            rec.message_post(body=note or self.env._(
                "The outstanding balance of %(amount)s will be recovered in the Full & Final Settlement "
                "(payroll of %(month)s).", amount=rec.currency_id.format(balance),
                month=last_day.strftime('%B %Y')))
            rec._check_closed()

    def action_open_fnf_wizard(self):
        self.ensure_one()
        if self.state != 'disbursed' or not self.env.user.has_group(HR_GROUP):
            raise UserError(self.env._("Only HR can settle an advance being recovered in the Full & Final Settlement."))
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Settle in Full & Final Settlement'),
            'res_model': 'bxi.salary.advance.fnf.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_advance_id': self.id},
        }

    # ── Payroll recovery ─────────────────────────────────────────────────
    def _notify_shortfall(self, payslip, shortfall):
        self.ensure_one()
        note = self.env._(
            "The net pay of payslip %(slip)s could not cover the salary advance EMI; %(amount)s is carried "
            "forward to the next payroll.", slip=payslip.number or payslip.name,
            amount=self.currency_id.format(shortfall))
        self.message_post(body=note)
        self._notify_group(
            self.company_id.sa_hr_user_id, HR_GROUP,
            self.env._("Salary advance EMI carried forward: %(employee)s", employee=self.employee_id.name), note)

    def _post_recovery_move(self, payslip, installments):
        """Credit the employee advance account with the EMIs deducted by a payslip."""
        self.ensure_one()
        company = self.company_id
        amount = self.currency_id.round(sum(installments.mapped('amount_recovered')))
        if not (installments and company.sa_recovery_account_id and company.sa_recovery_journal_id
                and company.sa_advance_account_id and self.disbursement_move_id) or self.currency_id.is_zero(amount):
            return
        label = self.env._("Salary advance %(name)s - EMI recovered (%(slip)s)",
                           name=self.name, slip=payslip.number or payslip.name)
        partner = self._get_employee_partner()
        move = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': company.sa_recovery_journal_id.id,
            'date': payslip.date_to,
            'ref': label,
            'company_id': company.id,
            'line_ids': [
                Command.create({
                    'name': label, 'account_id': company.sa_recovery_account_id.id,
                    'partner_id': partner.id, 'debit': amount, 'credit': 0.0,
                }),
                Command.create({
                    'name': label, 'account_id': company.sa_advance_account_id.id,
                    'partner_id': partner.id, 'debit': 0.0, 'credit': amount,
                }),
            ],
        })
        move.action_post()
        installments.move_id = move

    def _check_closed(self):
        for rec in self.sudo().filtered(lambda r: r.state in RECOVERY_STATES):
            if rec.installment_ids and not rec.installment_ids.filtered(lambda inst: inst.state == 'pending') \
                    and rec.currency_id.compare_amounts(rec.amount_balance, 0) <= 0:
                rec.write({'state': 'closed', 'closed_date': fields.Date.context_today(rec)})
                rec._reconcile_advance_lines()
                rec._notify_employee(self.env._("Salary advance %(name)s has been fully recovered.", name=rec.name))

    def _reopen(self):
        """A recovery was reverted (payslip cancelled): recovery continues."""
        for rec in self.sudo().filtered(lambda r: r.state == 'closed'):
            rec.write({'state': 'fnf' if rec.fnf_date else 'disbursed', 'closed_date': False})

    def _reconcile_advance_lines(self):
        self.ensure_one()
        account = self.company_id.sa_advance_account_id
        if not account.reconcile:
            return
        moves = self.disbursement_move_id | self.installment_ids.move_id
        lines = moves.line_ids.filtered(lambda line: line.account_id == account and not line.reconciled)
        if len(lines) > 1 and lines.company_currency_id.is_zero(sum(lines.mapped('balance'))):
            lines.reconcile()

    # ── Scheduled actions ────────────────────────────────────────────────
    @api.model
    def _cron_remind_and_escalate(self):
        """Remind Reporting Managers of pending approvals and escalate late HR processing."""
        now = fields.Datetime.now()
        reminder_days = int(self._get_param('rm_reminder_days', 2))
        if reminder_days:
            waiting = self.sudo().search([
                ('state', '=', 'submitted'),
                ('rm_reminder_sent', '=', False),
                ('submitted_date', '<=', now - relativedelta(days=reminder_days)),
            ])
            for rec in waiting:
                rec._notify_user(
                    rec.manager_id.user_id,
                    self.env._("Reminder: salary advance approval for %(employee)s", employee=rec.employee_id.name),
                    self.env._("Submitted on %(date)s.", date=fields.Date.to_date(rec.submitted_date)))
                rec.rm_reminder_sent = True
        for rec in self.sudo().search([('is_overdue', 'in', [True]), ('sla_escalated', '=', False)]):
            managers = self.env.ref('bxi_salary_advance.group_salary_advance_admin').all_user_ids.filtered(
                lambda user: rec.company_id in user.company_ids and not user.share)
            for user in managers:
                rec._notify_user(
                    user,
                    self.env._("Overdue salary advance: %(name)s", name=rec.name),
                    self.env._("HR processing was due by %(date)s (policy: 7 working days after the Reporting "
                               "Manager's approval).", date=rec.hr_deadline))
            rec.message_post(body=self.env._("Escalated: HR processing was due by %(date)s.", date=rec.hr_deadline))
            rec.sla_escalated = True

    # ── Navigation ───────────────────────────────────────────────────────
    def action_print_request_form(self):
        self.ensure_one()
        return self.env.ref('bxi_salary_advance.action_report_salary_advance_request').report_action(self)
