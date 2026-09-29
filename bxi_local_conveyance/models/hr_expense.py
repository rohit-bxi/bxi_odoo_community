from datetime import datetime, time

import pytz
from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, UserError

from .conveyance_approval_line import HR_GROUP
from .product_template import BILL_KINDS, TRAVEL_KINDS, VEHICLE_KINDS

PARAM_PREFIX = 'bxi_local_conveyance.'
PARAM_DEFAULTS = {
    'claim_days': 45,
    'reminder_days': 7,
    'auto_hr_threshold': 1000,
    'food_daily_limit': 1000,
    'non_working_day_mode': 'block',
}

# Fields that cannot change once a conveyance claim is submitted.
_LOCKED_FIELDS = {
    'total_amount', 'total_amount_currency', 'price_unit', 'quantity', 'product_id', 'employee_id',
    'currency_id', 'date', 'conveyance_purpose', 'conveyance_from', 'conveyance_to', 'conveyance_distance',
    'conveyance_airport_leg', 'conveyance_is_emergency', 'conveyance_reason', 'conveyance_within_city',
    'conveyance_parent_id', 'conveyance_bill_number', 'conveyance_bill_amount',
}


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    conveyance_kind = fields.Selection(related='product_id.conveyance_kind', store=True, string='Conveyance Type')
    state = fields.Selection(
        selection_add=[
            ('conveyance_approval', 'Conveyance Approval'),
            ('finance_approval',),
        ],
        ondelete={'conveyance_approval': 'set default'},
    )
    conveyance_purpose = fields.Selection(
        [
            ('client_visit', 'Client Location Visit'),
            ('official_visit', 'Other Official Destination'),
            ('airport', 'Residence - Airport (Official Travel)'),
            ('inter_site', 'Between Company Sites (Emergency)'),
        ],
        string='Purpose',
        help="Commuting between residence and workplace, travel for a training program and intercity travel "
             "are not covered by the Local Conveyance Policy.",
    )
    conveyance_from = fields.Char(string='From')
    conveyance_to = fields.Char(string='To')
    conveyance_distance = fields.Float(string='Distance (km)', digits=(16, 1))
    conveyance_airport_leg = fields.Selection(
        [('to_airport', 'Residence to Airport'), ('from_airport', 'Airport to Residence')],
        string='Airport Leg', help="One-way conveyance is reimbursed per leg at the per-km rate.")
    conveyance_is_emergency = fields.Boolean(
        string='Emergency', help="No inter-office cab was available and the employee had no personal transport.")
    conveyance_reason = fields.Text(
        string='Justification',
        help="Why it was an emergency, or why no auto-rickshaw was available for a taxi (travel plan TP3).")
    conveyance_within_city = fields.Boolean(
        string='Within Place of Posting',
        help="The employee declares the travel was within the city of their place of posting.")
    conveyance_parent_id = fields.Many2one(
        'hr.expense', string='Related Conveyance', index='btree_not_null', ondelete='restrict', copy=False,
        domain="[('employee_id', '=', employee_id), ('date', '=', date), "
               "('conveyance_kind', 'in', ('vehicle_2w', 'vehicle_4w', 'auto', 'taxi'))]",
        help="Parking and toll are claimed along with the conveyance claim of the same trip.")
    conveyance_bill_number = fields.Char(string='Bill / Receipt No.', copy=False)
    conveyance_bill_amount = fields.Monetary(
        string='Bill Amount', currency_field='company_currency_id', copy=False,
        help="Amount of the food bill. What exceeds the daily limit is borne by the employee.")
    conveyance_travel_plan_id = fields.Many2one(
        'bxi.conveyance.travel.plan', string='Travel Plan', readonly=True, copy=False)
    conveyance_rate = fields.Float(
        string='Rate per km', compute='_compute_conveyance_rate', digits='Product Price')
    conveyance_deadline = fields.Date(string='Claim By', compute='_compute_conveyance_deadline')
    conveyance_submit_date = fields.Date(string='Submitted On', readonly=True, copy=False)
    conveyance_policy_note = fields.Text(string='Policy Notes', readonly=True, copy=False)
    conveyance_refuse_reason = fields.Text(string='Refusal Reason', readonly=True, copy=False)
    conveyance_approval_line_ids = fields.One2many(
        'bxi.conveyance.approval.line', 'expense_id', string='Conveyance Approvals', copy=False)
    conveyance_can_approve = fields.Boolean(
        string='Conveyance to Approve', compute='_compute_conveyance_can_approve',
        search='_search_conveyance_can_approve')

    # ── Parameters ───────────────────────────────────────────────────────
    @api.model
    def _get_conveyance_param(self, key):
        default = PARAM_DEFAULTS[key]
        value = self.env['ir.config_parameter'].sudo().get_param(PARAM_PREFIX + key, default)
        if isinstance(default, str):
            return value or default
        try:
            return type(default)(float(value))
        except (TypeError, ValueError):
            return default

    # ── Computes ─────────────────────────────────────────────────────────
    @api.depends('conveyance_kind', 'price_unit')
    def _compute_conveyance_rate(self):
        for expense in self:
            expense.conveyance_rate = expense.price_unit if expense.conveyance_kind in VEHICLE_KINDS else 0.0

    @api.depends('date', 'conveyance_kind')
    def _compute_conveyance_deadline(self):
        days = self._get_conveyance_param('claim_days')
        for expense in self:
            expense.conveyance_deadline = (
                expense.date + relativedelta(days=days) if expense.date and expense.conveyance_kind else False)

    @api.depends_context('uid')
    @api.depends('state', 'conveyance_approval_line_ids.state')
    def _compute_conveyance_can_approve(self):
        for expense in self:
            line = expense._get_current_conveyance_line()
            expense.conveyance_can_approve = (
                expense.state == 'conveyance_approval' and bool(line) and line._is_approver(self.env.user))

    def _search_conveyance_can_approve(self, operator, value):
        if operator not in ('in', 'not in'):
            return NotImplemented
        pending = self.sudo().search([('state', '=', 'conveyance_approval')])
        user = self.env.user
        mine = pending.filtered(
            lambda exp: (line := exp._get_current_conveyance_line()) and line._is_approver(user))
        return [('id', operator, mine.ids)]

    def _get_current_conveyance_line(self):
        self.ensure_one()
        pending = self.sudo().conveyance_approval_line_ids.filtered(lambda line: line.state == 'pending')
        return pending.sorted('sequence')[:1]

    # ── Portal ───────────────────────────────────────────────────────────
    @api.model
    def _portal_expense_product_domain(self):
        # Conveyance is claimed from My Local Conveyance, where the policy rules apply.
        return super()._portal_expense_product_domain() + [('conveyance_kind', '=', False)]

    # ── CRUD ─────────────────────────────────────────────────────────────
    @api.onchange('conveyance_distance', 'product_id')
    def _onchange_conveyance_distance(self):
        if self.conveyance_kind in VEHICLE_KINDS and self.conveyance_distance:
            self.quantity = self.conveyance_distance

    def _sync_conveyance_quantity(self):
        """Personal vehicles are reimbursed per km: the quantity is the distance."""
        for expense in self.filtered(lambda exp: exp.conveyance_kind in VEHICLE_KINDS and exp.conveyance_distance):
            if expense.quantity != expense.conveyance_distance:
                expense.quantity = expense.conveyance_distance

    @api.model_create_multi
    def create(self, vals_list):
        expenses = super().create(vals_list)
        expenses._sync_conveyance_quantity()
        return expenses

    def write(self, vals):
        if not self.env.su and _LOCKED_FIELDS & vals.keys():
            if self.filtered(lambda exp: exp.conveyance_kind and exp.state != 'draft'):
                raise UserError(self.env._("Submitted conveyance claims cannot be modified."))
        res = super().write(vals)
        if {'conveyance_distance', 'product_id'} & vals.keys():
            self._sync_conveyance_quantity()
        return res

    # ── Policy rules ─────────────────────────────────────────────────────
    def _is_conveyance_non_working_day(self):
        """Whether the claim date is a weekend or a public holiday in the employee's working schedule."""
        self.ensure_one()
        employee = self.employee_id.sudo()
        calendar = employee.resource_calendar_id
        if not calendar or calendar.flexible_hours:
            return False
        tz = pytz.timezone(employee.tz or calendar.tz or 'UTC')
        start = tz.localize(datetime.combine(self.date, time.min))
        end = tz.localize(datetime.combine(self.date, time.max))
        unusual_days = calendar._get_unusual_days(start, end, employee.company_id)
        return unusual_days.get(fields.Date.to_string(self.date), False)

    def _get_conveyance_duplicate_bill(self):
        """Another claim filed with the same receipt or bill number (e.g. through the flexi basket)."""
        self.ensure_one()
        Expense = self.env['hr.expense'].sudo()
        claimed = [('id', '!=', self.id), ('state', 'not in', ('draft', 'refused'))]
        checksums = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'hr.expense'), ('res_id', '=', self.id),
        ]).mapped('checksum')
        if checksums:
            same_files = self.env['ir.attachment'].sudo().search([
                ('res_model', '=', 'hr.expense'), ('res_id', '!=', self.id), ('checksum', 'in', checksums),
            ])
            duplicate = Expense.search(claimed + [('id', 'in', same_files.mapped('res_id'))], limit=1)
            if duplicate:
                return duplicate
        if self.conveyance_bill_number:
            return Expense.search(claimed + [
                ('employee_id', '=', self.employee_id.id),
                ('conveyance_bill_number', '=ilike', self.conveyance_bill_number.strip()),
            ], limit=1)
        return Expense

    def _check_conveyance_policy(self):
        """Check the claim against the Local Conveyance Policy before it is submitted.

        Raise a UserError when a rule is broken. Return the notes that send the claim to HR for review.
        """
        self.ensure_one()
        _ = self.env._
        notes = []
        kind = self.conveyance_kind
        employee = self.employee_id.sudo()
        today = fields.Date.context_today(self)
        if not employee:
            raise UserError(_("%(claim)s: select the employee.", claim=self.name))
        if not self.date or self.date > today:
            raise UserError(_("%(claim)s: the date cannot be in the future.", claim=self.name))

        # Clause 8: claimed within 45 days of the transaction.
        claim_days = self._get_conveyance_param('claim_days')
        if today > self.date + relativedelta(days=claim_days):
            raise UserError(_(
                "%(claim)s: conveyance is claimed within %(days)s days of the transaction date (%(date)s).",
                claim=self.name, days=claim_days, date=self.date))

        # Clause 8: coverage ends after two months at another local office.
        assignment = self.env['bxi.conveyance.office.assignment']._get_uncovered(employee, self.date)
        if assignment:
            raise UserError(_(
                "%(claim)s: working from %(office)s since %(date)s, conveyance was covered until %(end)s only.",
                claim=self.name, office=assignment.work_location_id.name, date=assignment.date_from,
                end=assignment.coverage_end_date))

        if kind in BILL_KINDS and not self.nb_attachment:
            raise UserError(_("%(claim)s: attach the bill.", claim=self.name))

        # Clause 3: the same bill cannot be claimed again (e.g. already paid through the flexi basket).
        duplicate = self._get_conveyance_duplicate_bill()
        if duplicate:
            raise UserError(_(
                "%(claim)s: this bill has already been claimed in %(other)s.", claim=self.name, other=duplicate.name))

        if kind in TRAVEL_KINDS:
            notes += self._check_conveyance_trip()
        elif kind == 'parking_toll':
            self._check_conveyance_parking()
        elif kind == 'food':
            self._check_conveyance_food()

        if kind != 'food' and self.company_currency_id.compare_amounts(self.total_amount, 0) <= 0:
            raise UserError(_("%(claim)s: the amount must be greater than zero.", claim=self.name))
        return notes

    def _check_conveyance_trip(self):
        self.ensure_one()
        _ = self.env._
        notes = []
        kind = self.conveyance_kind
        if not self.conveyance_purpose:
            raise UserError(_("%(claim)s: select the purpose of the travel.", claim=self.name))
        if not (self.conveyance_from and self.conveyance_to):
            raise UserError(_("%(claim)s: enter where the travel started and ended.", claim=self.name))
        # Clause 4: intercity travel goes through HR and Finance (travel request).
        if not self.conveyance_within_city:
            raise UserError(_(
                "%(claim)s: only travel within your place of posting is local conveyance. Intercity travel is "
                "processed through HR and Finance with a travel request.", claim=self.name))
        if kind in VEHICLE_KINDS and self.conveyance_distance <= 0:
            raise UserError(_("%(claim)s: enter the distance travelled in km.", claim=self.name))

        # Clause 5: no transportation on weekends or holidays.
        if self._is_conveyance_non_working_day():
            if self._get_conveyance_param('non_working_day_mode') == 'block':
                raise UserError(_(
                    "%(claim)s: %(date)s is a weekend or holiday. Transportation is not provided for work on "
                    "weekends or holidays.", claim=self.name, date=self.date))
            notes.append(_("Claimed for a weekend or holiday (%(date)s).", date=self.date))

        # Exceptions: travel between company facilities uses the inter-office cabs.
        if self.conveyance_purpose == 'inter_site' and not (kind == 'auto' and self.conveyance_is_emergency):
            raise UserError(_(
                "%(claim)s: travel between company facilities uses the inter-office cabs. Only an auto-rickshaw in "
                "an emergency, when no cab is available, can be claimed.", claim=self.name))

        # Clause 7: residence to airport, one way at the per-km rates.
        if self.conveyance_purpose == 'airport':
            if kind not in VEHICLE_KINDS:
                raise UserError(_(
                    "%(claim)s: travel between residence and airport is reimbursed at the per-km rates of a "
                    "personal vehicle.", claim=self.name))
            if not self.conveyance_airport_leg:
                raise UserError(_("%(claim)s: select the airport leg.", claim=self.name))
            same_leg = self.sudo().search_count([
                ('id', '!=', self.id), ('employee_id', '=', self.employee_id.id), ('date', '=', self.date),
                ('conveyance_purpose', '=', 'airport'), ('conveyance_airport_leg', '=', self.conveyance_airport_leg),
                ('state', 'not in', ('draft', 'refused')),
            ])
            if same_leg:
                raise UserError(_(
                    "%(claim)s: this airport leg has already been claimed for %(date)s (one way only).",
                    claim=self.name, date=self.date))

        if kind in ('auto', 'taxi'):
            self._check_conveyance_mode()
        return notes

    def _check_conveyance_mode(self):
        """Clause 2 and the travel plan table: the mode of travel of the employee's band."""
        self.ensure_one()
        _ = self.env._
        employee = self.employee_id.sudo()
        plan = employee.conveyance_travel_plan_id
        if self.conveyance_is_emergency and not (self.conveyance_reason or '').strip():
            raise UserError(_("%(claim)s: describe the emergency.", claim=self.name))
        if self.conveyance_kind == 'auto' and self.conveyance_is_emergency:
            return
        if not plan:
            raise UserError(_(
                "%(claim)s: no travel plan matches the band of %(employee)s. Please contact HR.",
                claim=self.name, employee=employee.name))
        if self.conveyance_kind == 'auto' and not plan.allow_auto:
            raise UserError(_(
                "%(claim)s: travel plan %(plan)s travels by taxi. An auto-rickshaw is claimed only in an emergency.",
                claim=self.name, plan=plan.name))
        if self.conveyance_kind == 'taxi':
            if not plan.allow_taxi:
                raise UserError(_(
                    "%(claim)s: taxi is not part of travel plan %(plan)s.", claim=self.name, plan=plan.name))
            if plan.taxi_needs_reason and not (self.conveyance_reason or '').strip():
                raise UserError(_(
                    "%(claim)s: travel plan %(plan)s takes a taxi only where no auto-rickshaw is available. "
                    "Explain why no auto-rickshaw was available.", claim=self.name, plan=plan.name))

    def _check_conveyance_parking(self):
        """Clause 6: parking and toll are claimed along with the conveyance claim of the trip."""
        self.ensure_one()
        _ = self.env._
        parent = self.sudo().conveyance_parent_id
        if not parent:
            raise UserError(_(
                "%(claim)s: parking and toll are claimed along with a conveyance claim. Select it.", claim=self.name))
        if (parent.employee_id != self.employee_id or parent.date != self.date
                or parent.conveyance_kind not in TRAVEL_KINDS):
            raise UserError(_(
                "%(claim)s: the related conveyance must be your own travel claim of the same day.", claim=self.name))
        if parent.state == 'refused':
            raise UserError(_("%(claim)s: the related conveyance claim was refused.", claim=self.name))

    def _check_conveyance_food(self):
        """Food Policy: Sales Team only, at most the daily limit per employee; the excess is the employee's."""
        self.ensure_one()
        _ = self.env._
        employee = self.employee_id.sudo()
        if not employee.is_sales_team:
            raise UserError(_("%(claim)s: the Food Policy applies to the Sales Team only.", claim=self.name))
        currency = self.company_currency_id
        bill = self.conveyance_bill_amount or self.total_amount_currency
        if currency.compare_amounts(bill, 0) <= 0:
            raise UserError(_("%(claim)s: enter the amount of the bill.", claim=self.name))
        limit = self._get_conveyance_param('food_daily_limit')
        used = sum(self.sudo().search([
            ('id', '!=', self.id), ('employee_id', '=', employee.id), ('date', '=', self.date),
            ('conveyance_kind', '=', 'food'), ('state', 'not in', ('draft', 'refused')),
        ]).mapped('total_amount'))
        remaining = currency.round(limit - used)
        if currency.compare_amounts(remaining, 0) <= 0:
            raise UserError(_(
                "%(claim)s: the food limit of %(limit)s for %(date)s has already been claimed.",
                claim=self.name, limit=currency.format(limit), date=self.date))
        self.sudo().write({
            'conveyance_bill_amount': bill,
            'total_amount_currency': min(bill, remaining),
        })

    def _get_conveyance_info_notes(self):
        """Notes kept on the claim for information, which do not need HR to review it."""
        self.ensure_one()
        currency = self.company_currency_id
        capped = currency.compare_amounts(self.conveyance_bill_amount, self.total_amount) > 0
        if self.conveyance_kind == 'food' and capped:
            return [self.env._(
                "Food bill of %(bill)s capped at %(amount)s (daily limit); the excess is borne by the employee.",
                bill=currency.format(self.conveyance_bill_amount), amount=currency.format(self.total_amount))]
        return []

    def _needs_conveyance_hr_approval(self):
        """Auto-rickshaw above the threshold and parking and toll are approved by HR too."""
        self.ensure_one()
        if self.conveyance_kind == 'parking_toll':
            return True
        if self.conveyance_kind == 'auto':
            threshold = self._get_conveyance_param('auto_hr_threshold')
            return self.company_currency_id.compare_amounts(self.total_amount, threshold) > 0
        return False

    def _prepare_conveyance_approval_lines(self, needs_hr):
        """Reporting Manager, then HR when required."""
        self.ensure_one()
        employee = self.employee_id.sudo()
        manager_user = employee.parent_id.user_id
        if not manager_user:
            raise UserError(self.env._(
                "%(employee)s has no Reporting Manager with a user account. Please contact HR.",
                employee=employee.name))
        lines = [{'role': 'rm', 'approver_user_id': manager_user.id, 'sequence': 1}]
        hr_user = self.company_id.sudo().conveyance_hr_user_id
        if needs_hr and hr_user != manager_user:
            lines.append({'role': 'hr', 'approver_user_id': hr_user.id, 'sequence': 2})
        return lines

    # ── Workflow ─────────────────────────────────────────────────────────
    def action_submit(self):
        conveyance = self.filtered('conveyance_kind')
        if conveyance:
            conveyance._submit_conveyance()
        others = self - conveyance
        if others:
            return super(HrExpense, others).action_submit()
        return True

    def _submit_conveyance(self):
        user = self.env.user
        # Trips first: parking and toll are checked against the trip they come with.
        for expense in self.sorted(lambda exp: exp.conveyance_kind not in TRAVEL_KINDS):
            if expense.state != 'draft':
                raise UserError(self.env._("Only draft claims can be submitted."))
            if not self.env.su and expense.employee_id.user_id != user and not user.has_group(HR_GROUP):
                raise AccessError(self.env._("Only the employee or HR can submit the claim."))
            parent = expense.sudo().conveyance_parent_id
            if parent and parent.state == 'draft' and parent not in self:
                raise UserError(self.env._(
                    "%(claim)s: submit the related conveyance claim %(parent)s first, or together.",
                    claim=expense.name, parent=parent.name))
            expense._sync_conveyance_quantity()
            review_notes = expense._check_conveyance_policy()
            needs_hr = bool(review_notes) or expense._needs_conveyance_hr_approval()
            notes = review_notes + expense._get_conveyance_info_notes()
            lines = expense._prepare_conveyance_approval_lines(needs_hr)
            sudo_expense = expense.sudo()
            sudo_expense.conveyance_approval_line_ids.unlink()
            sudo_expense.write({
                'conveyance_travel_plan_id': expense.employee_id.sudo().conveyance_travel_plan_id.id,
                'conveyance_submit_date': fields.Date.context_today(expense),
                'conveyance_policy_note': '\n'.join(notes) or False,
                'conveyance_refuse_reason': False,
                'conveyance_approval_line_ids': [Command.create(vals) for vals in lines],
                'state': 'conveyance_approval',
            })
            if notes:
                sudo_expense.message_post(body='\n'.join(notes))
            expense._notify_conveyance_approver()

    def action_conveyance_approve(self):
        for expense in self:
            if not expense.conveyance_can_approve:
                raise UserError(self.env._("You are not allowed to approve %(claim)s.", claim=expense.name))
            line = expense._get_current_conveyance_line()
            line.sudo().write({'state': 'approved', 'date': fields.Datetime.now(), 'done_by_user_id': self.env.user.id})
            expense._close_conveyance_activities(self.env._("Approved"))
            if expense._get_current_conveyance_line():
                expense._notify_conveyance_approver()
            else:
                # Approvers may not have access to the employee's expenses.
                expense.sudo().write({'state': 'finance_approval'})
        return True

    def action_conveyance_refuse(self):
        for expense in self:
            if not expense.conveyance_can_approve:
                raise UserError(self.env._("You are not allowed to refuse %(claim)s.", claim=expense.name))
        return {
            'name': self.env._("Refuse Conveyance Claim"),
            'type': 'ir.actions.act_window',
            'res_model': 'bxi.conveyance.refuse.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_expense_ids': self.ids},
        }

    def _conveyance_refuse(self, reason):
        """Consequences: a claim not in line with the policy is denied."""
        for expense in self:
            if not expense.conveyance_can_approve:
                raise UserError(self.env._("You are not allowed to refuse %(claim)s.", claim=expense.name))
            expense._get_current_conveyance_line().sudo().write({
                'state': 'refused', 'date': fields.Datetime.now(), 'done_by_user_id': self.env.user.id,
                'comment': reason,
            })
            expense._close_conveyance_activities(self.env._("Refused"))
            expense.sudo().write({'state': 'refused', 'conveyance_refuse_reason': reason})
            expense._notify_conveyance_employee(self.env._(
                "Your conveyance claim %(claim)s has been refused: %(reason)s", claim=expense.name, reason=reason))

    # ── Notifications ────────────────────────────────────────────────────
    def _notify_conveyance_approver(self):
        self.ensure_one()
        line = self._get_current_conveyance_line()
        if not line:
            return
        expense = self.sudo()
        summary = self.env._("Conveyance claim to approve: %(employee)s", employee=expense.employee_id.name)
        note = self.env._(
            "%(claim)s - %(amount)s on %(date)s", claim=expense.name,
            amount=expense.company_currency_id.format(expense.total_amount), date=expense.date)
        users = line.approver_user_id or self.env.ref(HR_GROUP).sudo().all_user_ids.filtered(
            lambda user: expense.company_id in user.company_ids and not user.share)
        for user in users - expense.employee_id.user_id:
            expense.activity_schedule('mail.mail_activity_data_todo', user_id=user.id, summary=summary, note=note)

    def _close_conveyance_activities(self, feedback):
        todo = self.env.ref('mail.mail_activity_data_todo')
        activities = self.sudo().activity_ids.filtered(lambda act: act.activity_type_id == todo)
        mine = activities.filtered(lambda act: act.user_id == self.env.user)
        (mine or activities).action_feedback(feedback=feedback)
        # Other members of the HR group no longer need to act.
        (activities - mine).exists().unlink()

    def _notify_conveyance_employee(self, body):
        self.ensure_one()
        employee = self.employee_id.sudo()
        partner = employee.work_contact_id or employee.user_id.partner_id
        self.sudo().message_post(body=body, partner_ids=partner.ids, subtype_xmlid='mail.mt_comment')

    @api.model
    def _cron_conveyance_claim_reminder(self):
        """Remind employees of draft conveyance claims approaching the claim deadline."""
        today = fields.Date.context_today(self)
        claim_days = self._get_conveyance_param('claim_days')
        reminder_days = self._get_conveyance_param('reminder_days')
        todo = self.env.ref('mail.mail_activity_data_todo')
        drafts = self.sudo().search([
            ('conveyance_kind', '!=', False), ('state', '=', 'draft'),
            ('date', '>=', today - relativedelta(days=claim_days)),
            ('date', '<=', today - relativedelta(days=claim_days - reminder_days)),
        ])
        for expense in drafts:
            user = expense.employee_id.user_id
            if not user or user.share or expense.activity_ids.filtered(
                    lambda act: act.activity_type_id == todo and act.user_id == user):
                continue
            expense.activity_schedule(
                'mail.mail_activity_data_todo', date_deadline=expense.conveyance_deadline, user_id=user.id,
                summary=self.env._("Submit your conveyance claim by %(date)s", date=expense.conveyance_deadline))
