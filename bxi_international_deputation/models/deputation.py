from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .deputation_country_rule import SALARY_APPROACH
from .deputation_dates import CALENDAR, compute_outbound, compute_return

# Fields that decide the payroll dates; frozen once the employee is transferred.
OUTBOUND_FIELDS = {
    'arrival_date', 'host_country_id', 'rule_id', 'salary_approach',
    'annual_divisor', 'host_calendar_id', 'host_annual_gross', 'host_currency_id',
}
RETURN_FIELDS = {'return_landing_date'}
REMINDER_SUMMARY_START = 'Deputation: confirm arrival'
REMINDER_SUMMARY_END = 'Deputation: plan repatriation'


def _format_dates(dates):
    return ', '.join(day.strftime('%a %d %b %Y') for day in dates)


class BxiDeputation(models.Model):
    _name = 'bxi.deputation'
    _description = 'International Deputation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default='New', tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True, index=True)
    company_id = fields.Many2one(
        'res.company', string='Home Company', required=True, tracking=True,
        default=lambda self: self.env.company,
    )
    department_id = fields.Many2one(related='employee_id.department_id', store=True)
    manager_id = fields.Many2one(related='employee_id.parent_id', store=True, string='Manager')
    host_country_id = fields.Many2one('res.country', string='Host Country', required=True, tracking=True)
    host_company_id = fields.Many2one(
        'res.company', string='Host Entity', tracking=True,
        help='Company that runs the host country payroll, when it exists in Odoo.',
    )
    host_city = fields.Char(string='Host City')
    client_name = fields.Char(string='Client / Project')
    travel_request_id = fields.Many2one(
        'travel.request', string='Travel Request',
        domain="[('employee_id', '=', employee_id)]",
    )
    planned_start_date = fields.Date(string='Planned Travel Date', required=True, tracking=True)
    planned_end_date = fields.Date(string='Planned End Date', tracking=True)
    note = fields.Html(string='Notes')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('transferred', 'On Host Payroll'),
        ('returned', 'Returned'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)

    # ---------------------------------------------------------------
    # Salary approach (snapshot of the country rule)
    # ---------------------------------------------------------------
    rule_id = fields.Many2one(
        'bxi.deputation.country.rule', string='Country Rule',
        compute='_compute_rule_id', store=True, readonly=False,
    )
    salary_approach = fields.Selection(
        SALARY_APPROACH, string='Salary Approach', compute='_compute_rule_values',
        store=True, readonly=False, tracking=True,
    )
    annual_divisor = fields.Float(
        string='Annual Gross Divisor', compute='_compute_rule_values', store=True, readonly=False,
    )
    host_calendar_id = fields.Many2one(
        'resource.calendar', string='Host Working Calendar',
        compute='_compute_rule_values', store=True, readonly=False,
    )
    host_currency_id = fields.Many2one(
        'res.currency', string='Host Currency',
        compute='_compute_host_currency_id', store=True, readonly=False,
    )
    host_annual_gross = fields.Monetary(
        string='Host Annual Gross Salary', currency_field='host_currency_id', tracking=True,
        help='Fixed annual gross salary in the host country, used for the gap-day ex-gratia.',
    )
    gap_day_rate = fields.Monetary(
        string='Gap Day Rate', currency_field='host_currency_id', compute='_compute_gap_day_rate',
    )

    # ---------------------------------------------------------------
    # Transfer to the host payroll
    # ---------------------------------------------------------------
    arrival_date = fields.Date(
        string='Arrival Date', tracking=True, copy=False,
        help='Date of landing in the host country (host local date).',
    )
    home_last_date = fields.Date(
        string='Last Day on Home Payroll', compute='_compute_outbound', store=True, copy=False,
    )
    host_start_date = fields.Date(
        string='Deputation Commencement Date', compute='_compute_outbound', store=True, copy=False,
        help='First day on the host country payroll.',
    )
    outbound_gap_days = fields.Integer(string='Gap Days (Transfer)', compute='_compute_outbound', store=True)
    outbound_gap_dates = fields.Char(string='Gap Dates (Transfer)', compute='_compute_outbound', store=True)
    outbound_gap_amount = fields.Monetary(
        string='Ex-gratia on Transfer', currency_field='host_currency_id',
        compute='_compute_outbound', store=True,
        help='Paid by the host country with the first host payroll.',
    )

    # ---------------------------------------------------------------
    # Return to the home payroll
    # ---------------------------------------------------------------
    return_landing_date = fields.Date(
        string='Return Landing Date', tracking=True, copy=False,
        help='Date of landing back in the home country (home local date).',
    )
    host_last_date = fields.Date(
        string='Last Day on Host Payroll', compute='_compute_return', store=True, copy=False,
        help='Last working day in the host country; basis of the host final settlement.',
    )
    home_restart_date = fields.Date(
        string='Home Payroll Restart Date', compute='_compute_return', store=True, copy=False,
    )
    return_gap_days = fields.Integer(string='Gap Days (Return)', compute='_compute_return', store=True)
    return_gap_dates = fields.Char(string='Gap Dates (Return)', compute='_compute_return', store=True)
    return_gap_amount = fields.Monetary(
        string='Ex-gratia on Return', currency_field='host_currency_id',
        compute='_compute_return', store=True,
        help='Paid by the host country with the final settlement.',
    )

    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    approved_on = fields.Datetime(string='Approved On', readonly=True, copy=False)
    transferred_by_id = fields.Many2one('res.users', string='Transfer Confirmed By', readonly=True, copy=False)
    letter_sent = fields.Boolean(string='Commencement Letter Sent', readonly=True, copy=False)

    # ---------------------------------------------------------------
    # Computes
    # ---------------------------------------------------------------
    @api.depends('host_country_id', 'arrival_date', 'planned_start_date')
    def _compute_rule_id(self):
        Rule = self.env['bxi.deputation.country.rule']
        for rec in self:
            if rec.state in ('transferred', 'returned') and rec.rule_id:
                rec.rule_id = rec.rule_id
                continue
            rec.rule_id = Rule._get_rule(rec.host_country_id, rec.arrival_date or rec.planned_start_date)

    @api.depends('rule_id')
    def _compute_rule_values(self):
        for rec in self:
            if rec.state in ('transferred', 'returned') and rec.salary_approach:
                rec.update({
                    'salary_approach': rec.salary_approach,
                    'annual_divisor': rec.annual_divisor,
                    'host_calendar_id': rec.host_calendar_id,
                })
                continue
            rule = rec.rule_id
            rec.salary_approach = rule.salary_approach or CALENDAR
            rec.annual_divisor = rule.annual_divisor or 260.0
            rec.host_calendar_id = rule.calendar_id

    @api.depends('host_country_id')
    def _compute_host_currency_id(self):
        for rec in self:
            rec.host_currency_id = rec.host_country_id.currency_id or rec.company_id.currency_id

    @api.depends('host_annual_gross', 'annual_divisor')
    def _compute_gap_day_rate(self):
        for rec in self:
            rec.gap_day_rate = rec.host_annual_gross / rec.annual_divisor if rec.annual_divisor else 0.0

    def _is_working_day_function(self):
        self.ensure_one()
        return self.env['bxi.deputation.country.rule']._working_day_checker(self.host_calendar_id)

    def _gap_amount(self, gap_days):
        self.ensure_one()
        amount = self.gap_day_rate * gap_days
        return self.host_currency_id.round(amount) if self.host_currency_id else round(amount, 2)

    @api.depends('arrival_date', 'salary_approach', 'host_calendar_id', 'host_annual_gross', 'annual_divisor')
    def _compute_outbound(self):
        for rec in self:
            if not rec.arrival_date:
                rec.update({
                    'home_last_date': False, 'host_start_date': False, 'outbound_gap_days': 0,
                    'outbound_gap_dates': False, 'outbound_gap_amount': 0.0,
                })
                continue
            home_last, host_start, gaps = compute_outbound(
                rec.arrival_date, rec.salary_approach, rec._is_working_day_function())
            rec.update({
                'home_last_date': home_last,
                'host_start_date': host_start,
                'outbound_gap_days': len(gaps),
                'outbound_gap_dates': _format_dates(gaps) or False,
                'outbound_gap_amount': rec._gap_amount(len(gaps)),
            })

    @api.depends('return_landing_date', 'salary_approach', 'host_calendar_id', 'host_annual_gross', 'annual_divisor')
    def _compute_return(self):
        for rec in self:
            if not rec.return_landing_date:
                rec.update({
                    'host_last_date': False, 'home_restart_date': False, 'return_gap_days': 0,
                    'return_gap_dates': False, 'return_gap_amount': 0.0,
                })
                continue
            host_last, home_restart, gaps = compute_return(
                rec.return_landing_date, rec.salary_approach, rec._is_working_day_function())
            rec.update({
                'host_last_date': host_last,
                'home_restart_date': home_restart,
                'return_gap_days': len(gaps),
                'return_gap_dates': _format_dates(gaps) or False,
                'return_gap_amount': rec._gap_amount(len(gaps)),
            })

    # ---------------------------------------------------------------
    # Constraints
    # ---------------------------------------------------------------
    @api.constrains('planned_start_date', 'planned_end_date', 'arrival_date', 'return_landing_date',
                    'host_start_date', 'host_last_date')
    def _check_dates(self):
        for rec in self:
            if rec.planned_end_date and rec.planned_end_date < rec.planned_start_date:
                raise ValidationError(self.env._('The planned end date cannot be before the planned travel date.'))
            if rec.return_landing_date and rec.arrival_date and rec.return_landing_date <= rec.arrival_date:
                raise ValidationError(self.env._('The return landing date must be after the arrival date.'))
            if rec.host_last_date and rec.host_start_date and rec.host_last_date < rec.host_start_date:
                raise ValidationError(self.env._(
                    'The employee returns before the host payroll starts (%(start)s). '
                    'Check the arrival and return dates.', start=rec.host_start_date))

    @api.constrains('employee_id', 'state')
    def _check_single_active(self):
        for rec in self.filtered(lambda r: r.state in ('approved', 'transferred')):
            overlapping = self.search([
                ('id', '!=', rec.id),
                ('employee_id', '=', rec.employee_id.id),
                ('state', 'in', ('approved', 'transferred')),
            ], limit=1)
            if overlapping:
                raise ValidationError(self.env._(
                    '%(employee)s already has an active deputation (%(ref)s).',
                    employee=rec.employee_id.name, ref=overlapping.name))

    @api.constrains('host_country_id', 'company_id')
    def _check_host_country(self):
        for rec in self:
            if rec.host_country_id and rec.host_country_id == rec.company_id.country_id:
                raise ValidationError(self.env._('The host country must differ from the home company country.'))

    # ---------------------------------------------------------------
    # ORM
    # ---------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.deputation') or 'New'
            if vals.get('employee_id') and not vals.get('company_id'):
                employee = self.env['hr.employee'].browse(vals['employee_id'])
                vals['company_id'] = employee.company_id.id or self.env.company.id
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.user.has_group('bxi_international_deputation.group_deputation_manager'):
            for rec in self:
                if rec.state in ('transferred', 'returned') and OUTBOUND_FIELDS & set(vals):
                    raise UserError(self.env._(
                        '%s is already on the host payroll; the transfer details are locked. '
                        'Ask a Deputation Manager to correct them.', rec.name))
                if rec.state == 'returned' and RETURN_FIELDS & set(vals):
                    raise UserError(self.env._('%s is closed; the return details are locked.', rec.name))
        return super().write(vals)

    def unlink(self):
        if any(rec.state in ('transferred', 'returned') for rec in self):
            raise UserError(self.env._('A deputation that reached the host payroll cannot be deleted.'))
        return super().unlink()

    @api.onchange('travel_request_id')
    def _onchange_travel_request_id(self):
        request = self.travel_request_id
        if not request:
            return
        if request.to_country:
            self.host_country_id = request.to_country
        if request.departure_date:
            self.planned_start_date = request.departure_date
        if request.return_date and not self.planned_end_date:
            self.planned_end_date = request.return_date

    # ---------------------------------------------------------------
    # Workflow
    # ---------------------------------------------------------------
    def action_approve(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(self.env._('Only draft deputations can be approved.'))
            rec.write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approved_on': fields.Datetime.now(),
            })
        return True

    def action_confirm_arrival(self):
        """The employee landed in the host country: move them to the host payroll."""
        for rec in self:
            if rec.state != 'approved':
                raise UserError(self.env._('Approve the deputation before confirming the arrival.'))
            if not rec.arrival_date:
                raise UserError(self.env._('Enter the arrival date (date of landing in the host country).'))
            if rec.outbound_gap_days and not rec.host_annual_gross:
                raise UserError(self.env._(
                    'There are %s gap day(s): enter the host annual gross salary to compute the ex-gratia.',
                    rec.outbound_gap_days))
            rec.write({'state': 'transferred', 'transferred_by_id': self.env.user.id})
            rec.employee_id.sudo().write({'onsite_offshore': 'onsite'})
            rec.message_post(body=self.env._(
                'Transferred to the %(country)s payroll. Last day on the home payroll: %(last)s. '
                'Deputation commencement: %(start)s. Gap days: %(gaps)s.',
                country=rec.host_country_id.name, last=rec.home_last_date, start=rec.host_start_date,
                gaps=rec.outbound_gap_dates or self.env._('none')))
            rec._send_commencement_letter()
        return True

    def action_confirm_return(self):
        """The employee landed back home: move them back to the home payroll."""
        for rec in self:
            if rec.state != 'transferred':
                raise UserError(self.env._('Only deputations on the host payroll can be closed.'))
            if not rec.return_landing_date:
                raise UserError(self.env._('Enter the return landing date.'))
            if rec.return_gap_days and not rec.host_annual_gross:
                raise UserError(self.env._(
                    'There are %s gap day(s): enter the host annual gross salary to compute the ex-gratia.',
                    rec.return_gap_days))
            rec.write({'state': 'returned'})
            rec.employee_id.sudo().write({'onsite_offshore': 'offshore'})
            rec.message_post(body=self.env._(
                'Returned to the home payroll from %(restart)s. Last day on the host payroll '
                '(final settlement): %(last)s. Gap days: %(gaps)s.',
                restart=rec.home_restart_date, last=rec.host_last_date,
                gaps=rec.return_gap_dates or self.env._('none')))
            template = self.env.ref('bxi_international_deputation.mail_template_deputation_return',
                                    raise_if_not_found=False)
            if template and rec._employee_email():
                template.send_mail(rec.id, force_send=False)
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state in ('transferred', 'returned'):
                raise UserError(self.env._('A deputation on the host payroll cannot be cancelled; confirm the return instead.'))
            rec.state = 'cancelled'
        return True

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ('approved', 'cancelled'):
                raise UserError(self.env._('Only approved or cancelled deputations can be reset to draft.'))
            rec.write({'state': 'draft', 'approved_by_id': False, 'approved_on': False})
        return True

    def action_send_commencement_letter(self):
        for rec in self:
            if rec.state not in ('transferred', 'returned'):
                raise UserError(self.env._('The commencement letter is available once the arrival is confirmed.'))
            rec._send_commencement_letter()
        return True

    def action_print_commencement_letter(self):
        return self.env.ref('bxi_international_deputation.action_report_deputation_letter').report_action(self)

    def _employee_email(self):
        self.ensure_one()
        return self.employee_id.work_email or self.employee_id.user_id.email

    def _send_commencement_letter(self):
        """Notify the employee of the deputation start date (policy objective)."""
        self.ensure_one()
        template = self.env.ref('bxi_international_deputation.mail_template_deputation_commencement',
                                raise_if_not_found=False)
        if not template or not self._employee_email():
            self.message_post(body=self.env._(
                'The commencement letter was not emailed: the employee has no work email.'))
            return
        template.send_mail(self.id, force_send=False)
        self.letter_sent = True

    # ---------------------------------------------------------------
    # Payroll helpers
    # ---------------------------------------------------------------
    def _off_home_payroll_range(self):
        """(first, last) days the employee is NOT on the home payroll; ``last`` may be None."""
        self.ensure_one()
        if self.state not in ('transferred', 'returned') or not self.home_last_date:
            return None
        first = self.home_last_date + timedelta(days=1)
        last = self.home_restart_date - timedelta(days=1) if self.home_restart_date else None
        return first, last

    # ---------------------------------------------------------------
    # Reminders
    # ---------------------------------------------------------------
    @api.model
    def _cron_deputation_reminders(self):
        today = fields.Date.context_today(self)
        late_arrivals = self.search([('state', '=', 'approved'), ('planned_start_date', '<', today)])
        for rec in late_arrivals:
            rec._schedule_reminder(
                REMINDER_SUMMARY_START,
                self.env._('The planned travel date %s has passed. Enter the arrival date and confirm the transfer.',
                           rec.planned_start_date))
        ending = self.search([
            ('state', '=', 'transferred'),
            ('planned_end_date', '!=', False),
            ('planned_end_date', '<=', today + timedelta(days=30)),
        ])
        for rec in ending:
            rec._schedule_reminder(
                REMINDER_SUMMARY_END,
                self.env._('The deputation is planned to end on %s. Plan the repatriation and the host final settlement.',
                           rec.planned_end_date))

    def _schedule_reminder(self, summary, note):
        self.ensure_one()
        if self.activity_ids.filtered(lambda a: a.summary == summary):
            return
        user = self.approved_by_id or self.create_uid
        self.activity_schedule('mail.mail_activity_data_todo', summary=summary, note=note, user_id=user.id)
