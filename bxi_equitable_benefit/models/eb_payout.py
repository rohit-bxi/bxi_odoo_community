import calendar
import logging
from datetime import date, datetime, time, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .eb_eligibility import RATING_ORDER

_logger = logging.getLogger(__name__)

PARAM_PREFIX = 'bxi_equitable_benefit.'
WEEKDAY_LOCATION_FIELDS = (
    'monday_location_id', 'tuesday_location_id', 'wednesday_location_id', 'thursday_location_id',
    'friday_location_id', 'saturday_location_id', 'sunday_location_id',
)


def _month_fraction(date_from, date_to):
    """Number of months covered by [date_from, date_to], partial months counted by days."""
    months = 0.0
    cursor = date_from
    while cursor <= date_to:
        month_days = calendar.monthrange(cursor.year, cursor.month)[1]
        month_end = cursor.replace(day=month_days)
        chunk_end = min(month_end, date_to)
        months += ((chunk_end - cursor).days + 1) / month_days
        cursor = month_end + timedelta(days=1)
    return months


def _overlap_days(start1, end1, start2, end2):
    start, end = max(start1, start2), min(end1, end2)
    return (end - start).days + 1 if start <= end else 0


def _date_range(date_from, date_to):
    return {date_from + timedelta(days=offset) for offset in range((date_to - date_from).days + 1)}


class BxiEbPayout(models.Model):
    _name = 'bxi.eb.payout'
    _description = 'Equitable Benefit Payout'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'bxi.eb.notify.mixin']
    _order = 'fy_start desc, employee_id'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    employee_id = fields.Many2one('hr.employee', required=True, index=True, tracking=True)
    company_id = fields.Many2one(related='employee_id.company_id', store=True)
    department_id = fields.Many2one(related='employee_id.department_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    payout_type = fields.Selection([
        ('annual', 'Annual'),
        ('fnf', 'Full & Final Settlement'),
    ], default='annual', required=True, tracking=True)
    fy_start = fields.Date(
        string='Financial Year Start', required=True,
        help="Any date in the financial year: it is moved to the first day of that year.")
    fy_end = fields.Date(
        string='Financial Year End', required=True, compute='_compute_fy_end', store=True, readonly=False)
    fy_name = fields.Char(string='Financial Year', compute='_compute_fy_name', store=True)
    period_end = fields.Date(
        string='Eligibility Period End', required=True, compute='_compute_period_end', store=True, readonly=False,
        help="End of the financial year, or the last working day for a Full & Final Settlement.")
    resignation_id = fields.Many2one('employee.resignation', readonly=True)
    separation_date = fields.Date(
        readonly=True, tracking=True, copy=False,
        help="Last working day of a separating employee. The payout is settled in the Full & Final "
             "Settlement, including an earlier year not paid yet.")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('validated', 'Validated'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)

    # Eligibility snapshot, refreshed by action_compute
    disciplinary_count = fields.Integer(readonly=True)
    rating = fields.Char(string='Performance Rating', readonly=True)
    unauthorized_absence_days = fields.Float(readonly=True)
    unpaid_leave_days = fields.Float(readonly=True)
    unpaid_leave_prorated = fields.Boolean(string='Unpaid Leave Pro-rated', readonly=True)
    is_eligible = fields.Boolean(string='Eligible', readonly=True)
    ineligibility_reason = fields.Text(readonly=True)
    warning_note = fields.Text(
        string='Review Notes', readonly=True,
        help="Points Revenue Assurance should check before validating. They do not block the payout.")
    missing_component_a = fields.Boolean(string='Component A Missing', readonly=True)
    computed_date = fields.Datetime(readonly=True, copy=False)

    line_ids = fields.One2many('bxi.eb.payout.line', 'payout_id', string='Computation Lines', copy=False)
    amount_computed = fields.Monetary(readonly=True, tracking=True)

    # Exceptions (Governance: written approval by designated leadership)
    is_exception = fields.Boolean(string='Approved Exception', tracking=True)
    exception_amount = fields.Monetary(tracking=True)
    exception_reason = fields.Text()
    exception_approver_id = fields.Many2one(
        'res.users', string='Approved By (Leadership)', tracking=True,
        domain=lambda self: [('all_group_ids', 'in', self.env.ref(
            'bxi_equitable_benefit.group_eb_leadership', raise_if_not_found=False).ids)])
    exception_attachment_ids = fields.Many2many(
        'ir.attachment', 'bxi_eb_payout_exception_attachment_rel', 'payout_id', 'attachment_id',
        string='Written Approval')
    amount_final = fields.Monetary(string='Payout Amount', compute='_compute_amount_final', store=True, tracking=True)

    payout_date = fields.Date(
        string='Payroll Date', tracking=True,
        help="The payout is added to the payslip whose period contains this date.")
    payslip_id = fields.Many2one('hr.payslip', readonly=True, copy=False)
    validated_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    approved_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    rejection_reason = fields.Text(copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.eb.payout') or 'New'
        return super().create(vals_list)

    def unlink(self):
        if any(rec.state not in ('draft', 'cancelled', 'rejected') for rec in self):
            raise UserError(_("Only draft, rejected or cancelled payouts can be deleted."))
        return super().unlink()

    @api.onchange('fy_start')
    def _onchange_fy_start(self):
        if self.fy_start:
            self.fy_start = self._get_fy_bounds(self.fy_start)[0]

    @api.depends('fy_start')
    def _compute_fy_end(self):
        for rec in self:
            if rec.fy_start:
                rec.fy_end = rec._get_fy_bounds(rec.fy_start)[1]

    @api.depends('fy_start', 'fy_end', 'payout_type')
    def _compute_period_end(self):
        """The whole year for an annual payout; a settlement keeps its last working day when it fits."""
        for rec in self:
            if not rec.fy_end:
                continue
            if rec.payout_type == 'annual' or not rec.period_end \
                    or not rec.fy_start <= rec.period_end <= rec.fy_end:
                rec.period_end = rec.fy_end

    @api.depends('fy_start', 'fy_end')
    def _compute_fy_name(self):
        for rec in self:
            if rec.fy_start and rec.fy_end and rec.fy_start.year != rec.fy_end.year:
                rec.fy_name = 'FY %s-%s' % (rec.fy_start.year, str(rec.fy_end.year)[2:])
            else:
                rec.fy_name = rec.fy_start and 'FY %s' % rec.fy_start.year

    @api.depends('amount_computed', 'is_exception', 'exception_amount')
    def _compute_amount_final(self):
        for rec in self:
            rec.amount_final = rec.exception_amount if rec.is_exception else rec.amount_computed

    @api.constrains('employee_id', 'fy_start', 'state')
    def _check_unique(self):
        for rec in self.filtered(lambda r: r.state not in ('rejected', 'cancelled')):
            if self.search_count([
                ('id', '!=', rec.id),
                ('employee_id', '=', rec.employee_id.id),
                ('fy_start', '=', rec.fy_start),
                ('state', 'not in', ('rejected', 'cancelled')),
            ], limit=1):
                raise ValidationError(_(
                    "%(employee)s already has an equitable benefit payout for %(fy)s.",
                    employee=rec.employee_id.name, fy=rec.fy_name))

    @api.constrains('fy_start', 'fy_end', 'period_end')
    def _check_period(self):
        for rec in self:
            if rec.fy_end < rec.fy_start:
                raise ValidationError(_("The financial year of %(payout)s ends (%(end)s) before it starts (%(start)s).",
                                        payout=rec.name, end=rec.fy_end, start=rec.fy_start))
            if not rec.fy_start <= rec.period_end <= rec.fy_end:
                raise ValidationError(_(
                    "The eligibility period end of %(payout)s (%(period_end)s) must fall within the financial "
                    "year %(start)s to %(end)s.",
                    payout=rec.name, period_end=rec.period_end, start=rec.fy_start, end=rec.fy_end))

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    @api.model
    def _get_param(self, key, default):
        return self.env['ir.config_parameter'].sudo().get_param(PARAM_PREFIX + key, default)

    @api.model
    def _get_fy_bounds(self, day):
        start_month = int(self._get_param('fy_start_month', 4))
        start = date(day.year if day.month >= start_month else day.year - 1, start_month, 1)
        return start, start + relativedelta(years=1, days=-1)

    def _get_suspended_from(self):
        """First day the policy no longer applies to the company (Governance: modify, suspend or withdraw)."""
        return (self.company_id or self.env.company).sudo().eb_suspended_from or None

    # ------------------------------------------------------------------
    # Leave and attendance
    # ------------------------------------------------------------------
    def _leave_days(self, flag, date_from, date_to):
        """Approved leave days in the period, optionally only of types with ``flag`` set.

        Uses the leave duration (working days), pro-rated by calendar days when the
        leave only partly falls in the period.
        """
        domain = [
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'validate'),
            ('request_date_from', '<=', date_to),
            ('request_date_to', '>=', date_from),
        ]
        if flag:
            domain.append(('holiday_status_id.%s' % flag, '=', True))
        leaves = self.env['hr.leave'].sudo().search(domain)
        days = 0.0
        for leave in leaves:
            span = (leave.request_date_to - leave.request_date_from).days + 1
            days += leave.number_of_days * _overlap_days(
                leave.request_date_from, leave.request_date_to, date_from, date_to) / span
        return leaves, round(days, 2)

    def _employee_tz(self):
        return pytz.timezone(self.employee_id.sudo().tz or self.env.user.tz or 'UTC')

    def _utc_bounds(self, date_from, date_to):
        """Naive UTC datetimes delimiting the local days [date_from, date_to]."""
        tz = self._employee_tz()
        start = tz.localize(datetime.combine(date_from, time.min)).astimezone(pytz.utc)
        stop = tz.localize(datetime.combine(date_to + timedelta(days=1), time.min)).astimezone(pytz.utc)
        return start.replace(tzinfo=None), stop.replace(tzinfo=None)

    def _first_attendance_date(self):
        """Day the employee's attendance was first recorded, or None (no attendance tracking)."""
        if 'hr.attendance' not in self.env:
            return None
        first = self.env['hr.attendance'].sudo().search(
            [('employee_id', '=', self.employee_id.id)], order='check_in', limit=1)
        if not first:
            return None
        return pytz.utc.localize(first.check_in).astimezone(self._employee_tz()).date()

    def _attended_dates(self, date_from, date_to):
        start, stop = self._utc_bounds(date_from, date_to)
        attendances = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', self.employee_id.id),
            ('check_in', '>=', start),
            ('check_in', '<', stop),
        ])
        tz = self._employee_tz()
        return {pytz.utc.localize(att.check_in).astimezone(tz).date() for att in attendances}

    def _measurable_period(self, date_from, date_to, first_attendance):
        """Part of the period covered by attendance tracking and already past."""
        if not first_attendance:
            return None, None
        date_from = max(date_from, first_attendance)
        date_to = min(date_to, fields.Date.context_today(self) - timedelta(days=1))
        return (date_from, date_to) if date_from <= date_to else (None, None)

    def _absent_dates(self, date_from, date_to, first_attendance):
        """Working days without attendance and without approved leave (unauthorized absence)."""
        date_from, date_to = self._measurable_period(date_from, date_to, first_attendance)
        employee = self.employee_id.sudo()
        if not date_from or not employee.resource_calendar_id:
            return set()
        tz = self._employee_tz()
        start = tz.localize(datetime.combine(date_from, time.min))
        stop = tz.localize(datetime.combine(date_to, time.max))
        intervals = employee.resource_calendar_id._work_intervals_batch(
            start, stop, resources=employee.resource_id, tz=tz)[employee.resource_id.id]
        work_dates = {interval[0].astimezone(tz).date() for interval in intervals}
        leaves, _days = self._leave_days(False, date_from, date_to)
        on_leave = set()
        for leave in leaves:
            on_leave |= _date_range(leave.request_date_from, leave.request_date_to)
        return work_dates - on_leave - self._attended_dates(date_from, date_to)

    def _public_holiday_dates(self, date_from, date_to):
        employee = self.employee_id.sudo()
        start, stop = self._utc_bounds(date_from, date_to)
        holidays = self.env['resource.calendar.leaves'].sudo().search([
            ('resource_id', '=', False),
            ('calendar_id', 'in', (employee.resource_calendar_id.id, False)),
            ('company_id', 'in', (employee.company_id.id, False)),
            ('date_from', '<', stop),
            ('date_to', '>', start),
        ])
        tz = self._employee_tz()
        dates = set()
        for holiday in holidays:
            dates |= _date_range(pytz.utc.localize(holiday.date_from).astimezone(tz).date(),
                                 pytz.utc.localize(holiday.date_to).astimezone(tz).date())
        return {day for day in dates if date_from <= day <= date_to}

    def _is_home_day(self, day):
        """Whether the employee's effective work location on ``day`` is home (WFH)."""
        employee = self.employee_id.sudo()
        Attendance = self.env['hr.attendance'].sudo()
        if hasattr(Attendance, '_get_effective_work_location'):
            location = Attendance._get_effective_work_location(employee, day)
        else:
            field_name = WEEKDAY_LOCATION_FIELDS[day.weekday()]
            location = employee[field_name] if field_name in employee._fields else False
        return bool(location) and (location.location_type == 'home' or bool(getattr(location, 'home', False)))

    def _pattern_compliance(self, pattern, date_from, date_to, first_attendance):
        """Return (expected, attended) office days for the pattern, or None when not measurable."""
        if not pattern.days_per_week:
            return None
        date_from, date_to = self._measurable_period(date_from, date_to, first_attendance)
        if not date_from:
            return None
        days_per_week = pattern.days_per_week
        weekend = {6} if days_per_week > 5 else {5, 6}
        holidays = {day for day in self._public_holiday_dates(date_from, date_to)
                    if day.weekday() not in weekend or days_per_week >= 7}
        _leaves, leave_days = self._leave_days(False, date_from, date_to)
        days = (date_to - date_from).days + 1
        expected = max(days_per_week * days / 7 - len(holidays) - leave_days, 0.0)
        attended = {day for day in self._attended_dates(date_from, date_to) if not self._is_home_day(day)}
        return round(expected, 1), len(attended)

    # ------------------------------------------------------------------
    # Computation
    # ------------------------------------------------------------------
    def action_compute(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft payouts can be recomputed."))
            rec._compute_payout()

    def _disciplinary_cases(self, start, end):
        """Compliance cases closed with a disciplinary outcome, active during the period."""
        if 'antitrust.case' not in self.env:
            return 0
        return self.env['antitrust.case'].sudo().search_count([
            ('employee_ids', 'in', self.employee_id.id),
            ('outcome', '=', 'disciplinary'),
            ('create_date', '<', datetime.combine(end + timedelta(days=1), time.min)),
            '|', ('closed_date', '=', False), ('closed_date', '>=', start),
        ])

    def _find_rating(self):
        """Return (rating, note). A separation falls back to the latest earlier rating."""
        Rating = self.env['bxi.eb.performance.rating'].sudo()
        rating = Rating.search([('employee_id', '=', self.employee_id.id), ('fy_start', '=', self.fy_start)], limit=1)
        if rating or not self.separation_date or self._get_param('fnf_rating', 'latest') != 'latest':
            return rating, False
        rating = Rating.search([
            ('employee_id', '=', self.employee_id.id), ('fy_start', '<', self.fy_start),
        ], order='fy_start desc', limit=1)
        return rating, rating and _(
            "No performance rating for %(fy)s yet: the latest available rating (%(previous)s) was used "
            "for the separation.", fy=self.fy_name, previous=rating.fy_name)

    def _check_eligibility(self):
        """Return (eligible, reasons, warnings, values to write)."""
        self.ensure_one()
        reasons, warnings = [], []
        start, end = self.fy_start, self.period_end

        disciplinary = self.env['bxi.eb.disciplinary.action'].sudo()._overlapping(self.employee_id, start, end)
        if disciplinary:
            reasons.append(_("Disciplinary action during the eligibility period: %s",
                             ', '.join(disciplinary.mapped('name'))))
        compliance_cases = self._disciplinary_cases(start, end)
        if compliance_cases:
            reasons.append(_("Disciplinary outcome on %s compliance case(s) during the eligibility period.",
                             compliance_cases))

        rating, rating_note = self._find_rating()
        if rating_note:
            warnings.append(rating_note)
        min_rating = self._get_param('min_rating', 'meets')
        if rating:
            if RATING_ORDER[rating.rating] < RATING_ORDER.get(min_rating, 1):
                reasons.append(_("Performance rating '%s' is below the required level.",
                                 dict(rating._fields['rating'].selection)[rating.rating]))
        elif not self._get_param('allow_missing_rating', False):
            reasons.append(_("No performance rating recorded for this financial year."))

        _leaves, unauthorized = self._leave_days('eb_is_unauthorized', start, end)
        if self._get_param('absence_source', 'attendance') == 'attendance':
            unauthorized += len(self._absent_dates(start, end, self._first_attendance_date()))
        max_unauthorized = float(self._get_param('max_unauthorized_days', 0))
        if unauthorized > max_unauthorized:
            reasons.append(_("Unauthorized absence of %(days)s days exceeds the allowed %(max)s days.",
                             days=unauthorized, max=max_unauthorized))

        _leaves, unpaid = self._leave_days('eb_is_unpaid', start, end)
        return not reasons, reasons, warnings, {
            'disciplinary_count': len(disciplinary) + compliance_cases,
            'rating': rating and '%s%s' % (
                dict(rating._fields['rating'].selection)[rating.rating],
                ' (%s)' % rating.fy_name if rating.fy_start != self.fy_start else '') or False,
            'unauthorized_absence_days': unauthorized,
            'unpaid_leave_days': unpaid,
            'unpaid_leave_prorated': unpaid > float(self._get_param('unpaid_leave_threshold_days', 0)),
        }

    def _get_segments(self):
        """Split approved assignments into periods with a constant rate and Component A."""
        self.ensure_one()
        Rate = self.env['bxi.eb.rate'].sudo()
        employee = self.employee_id.sudo()
        period_end = self.period_end
        suspended_from = self._get_suspended_from()
        if suspended_from:
            period_end = min(period_end, suspended_from - timedelta(days=1))
        assignments = self.env['bxi.eb.assignment'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'approved'),
            ('date_from', '<=', period_end),
            '|', ('date_to', '=', False), ('date_to', '>=', self.fy_start),
        ], order='date_from')
        version_dates = set(employee.with_context(active_test=False).version_ids.mapped('date_version'))
        segments = []
        for assignment in assignments:
            seg_from = max(assignment.date_from, self.fy_start)
            seg_to = min(assignment.date_to or period_end, period_end)
            rates = Rate.search([('work_pattern_id', '=', assignment.work_pattern_id.id)])
            cuts = {d for d in version_dates if seg_from < d <= seg_to}
            cuts |= {r.date_from for r in rates if seg_from < r.date_from <= seg_to}
            cuts |= {r.date_to + timedelta(days=1) for r in rates if r.date_to and seg_from <= r.date_to < seg_to}
            starts = sorted({seg_from} | cuts)
            for index, start in enumerate(starts):
                stop = starts[index + 1] - timedelta(days=1) if index + 1 < len(starts) else seg_to
                rate = Rate._find_rate(assignment.work_pattern_id, assignment.work_category,
                                       assignment.deployment, start, assignment.company_id)
                segments.append({
                    'assignment': assignment,
                    'date_from': start,
                    'date_to': stop,
                    'rate': rate,
                    'component_a': employee._get_version(start).eb_annual_component_a,
                })
        return segments

    def _compute_payout(self):
        self.ensure_one()
        eligible, reasons, warnings, values = self._check_eligibility()
        basis = self._get_param('proration_basis', 'months')
        fy_days = (self.fy_end - self.fy_start).days + 1
        min_compliance = float(self._get_param('min_pattern_compliance', 0))
        first_attendance = self._first_attendance_date()
        missing_component_a = False
        line_vals = []
        for seg in self._get_segments():
            days = (seg['date_to'] - seg['date_from']).days + 1
            unpaid = 0
            if values['unpaid_leave_prorated']:
                _leaves, unpaid = self._leave_days('eb_is_unpaid', seg['date_from'], seg['date_to'])
            if basis == 'days':
                fraction = (days - unpaid) / fy_days
            else:
                fraction = _month_fraction(seg['date_from'], seg['date_to']) / 12 * (days - unpaid) / days
            rate_percent = seg['rate'].rate_percent
            pattern = seg['assignment'].work_pattern_id
            vals = {
                'assignment_id': seg['assignment'].id,
                'work_pattern_id': pattern.id,
                'rate_id': seg['rate'].id,
                'date_from': seg['date_from'],
                'date_to': seg['date_to'],
                'days': days,
                'unpaid_days': unpaid,
                'fraction': fraction,
                'component_a': seg['component_a'],
                'rate_percent': rate_percent,
                'amount': self.currency_id.round(seg['component_a'] * rate_percent / 100 * fraction),
            }
            compliance = rate_percent and self._pattern_compliance(
                pattern, seg['date_from'], seg['date_to'], first_attendance)
            if compliance:
                expected, attended = compliance
                percent = min(attended / expected * 100, 100.0) if expected else 100.0
                vals.update(expected_days=expected, attended_days=attended,
                            compliance_percent=percent, compliance_checked=True)
                if percent < min_compliance:
                    warnings.append(_(
                        "%(pattern)s from %(date_from)s to %(date_to)s: %(attended)s office days attended out "
                        "of %(expected)s expected (%(percent)s%%).",
                        pattern=pattern.name, date_from=seg['date_from'], date_to=seg['date_to'],
                        attended=attended, expected=expected, percent='%.0f' % percent))
            if rate_percent and not seg['component_a']:
                missing_component_a = True
            line_vals.append((0, 0, vals))
        if not line_vals:
            suspended_from = self._get_suspended_from()
            if suspended_from and suspended_from <= self.period_end:
                reasons.append(_("The policy is suspended from %s.", suspended_from))
            else:
                reasons.append(_("No approved work pattern assignment in the eligibility period."))
            eligible = False
        if missing_component_a:
            warnings.append(_("Annualized Component A is not set on the employee's contract for part of the "
                              "period, so that part pays nothing."))
        self.line_ids.unlink()
        values.update({
            'line_ids': line_vals,
            'is_eligible': eligible,
            'ineligibility_reason': '\n'.join(reasons) or False,
            'warning_note': '\n'.join(warnings) or False,
            'missing_component_a': missing_component_a,
            'computed_date': fields.Datetime.now(),
        })
        self.write(values)
        self.amount_computed = sum(self.line_ids.mapped('amount')) if eligible else 0.0

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_validate(self):
        if not self.env.user.has_group('bxi_equitable_benefit.group_eb_revenue_assurance'):
            raise UserError(_("Only Revenue Assurance can validate equitable benefit payouts."))
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft payouts can be validated."))
            if not rec.computed_date:
                raise UserError(_("Compute the payout before validating it."))
            if rec.is_exception:
                if not (rec.exception_reason and rec.exception_approver_id
                        and rec.sudo().exception_attachment_ids):
                    raise UserError(_("An exception needs a reason, the approving leader and "
                                      "the written approval attached."))
                if not rec.exception_approver_id.has_group('bxi_equitable_benefit.group_eb_leadership'):
                    raise UserError(_("%s is not a designated leadership authority for Equitable Benefit "
                                      "exceptions.", rec.exception_approver_id.name))
            elif rec.is_eligible and rec.missing_component_a:
                raise UserError(_(
                    "Set the Annualized Component A on %s's contract and recompute before validating.",
                    rec.employee_id.name))
        self.write({'state': 'validated', 'validated_by_id': self.env.user.id})
        self._eb_close_activities()

    def action_approve(self):
        if not self.env.user.has_group('bxi_equitable_benefit.group_eb_finance'):
            raise UserError(_("Only Finance can approve equitable benefit payouts."))
        for rec in self:
            if rec.state != 'validated':
                raise UserError(_("Only validated payouts can be approved."))
            if not rec.payout_date:
                rec.payout_date = rec._default_payout_date()
        self.write({'state': 'approved', 'approved_by_id': self.env.user.id})

    def action_reject(self):
        if not self.env.user.has_group('bxi_equitable_benefit.group_eb_revenue_assurance') and \
                not self.env.user.has_group('bxi_equitable_benefit.group_eb_finance'):
            raise UserError(_("You are not allowed to reject equitable benefit payouts."))
        if any(rec.state not in ('draft', 'validated') for rec in self):
            raise UserError(_("Only draft or validated payouts can be rejected."))
        self.write({'state': 'rejected'})
        self._eb_close_activities()

    def action_cancel(self):
        if any(rec.state == 'paid' or rec.payslip_id for rec in self):
            raise UserError(_("Payouts already included in a payslip cannot be cancelled."))
        self.write({'state': 'cancelled'})
        self._eb_close_activities()

    def action_reset_draft(self):
        if any(rec.state == 'paid' or rec.payslip_id for rec in self):
            raise UserError(_("Payouts already included in a payslip cannot be reset."))
        self.write({'state': 'draft', 'validated_by_id': False, 'approved_by_id': False})

    def _default_payout_date(self):
        self.ensure_one()
        if self.separation_date:
            return self.separation_date
        return self.period_end if self.payout_type == 'fnf' else self.fy_end + timedelta(days=1)

    # ------------------------------------------------------------------
    # Annual cycle
    # ------------------------------------------------------------------
    @api.model
    def _generate_annual_payouts(self, fy_start, fy_end, employees=None):
        """Create or recompute draft annual payouts for the financial year.

        Employees whose assignments carry no benefit (e.g. Hybrid, Not Applicable) are skipped.
        """
        paying_patterns = self.env['bxi.eb.rate'].search([
            ('rate_percent', '>', 0),
            ('date_from', '<=', fy_end),
            '|', ('date_to', '=', False), ('date_to', '>=', fy_start),
        ]).work_pattern_id
        domain = [
            ('state', '=', 'approved'),
            ('work_pattern_id', 'in', paying_patterns.ids),
            ('date_from', '<=', fy_end),
            '|', ('date_to', '=', False), ('date_to', '>=', fy_start),
        ]
        if employees:
            domain.append(('employee_id', 'in', employees.ids))
        employees = self.env['bxi.eb.assignment'].search(domain).employee_id
        existing = self.search([
            ('fy_start', '=', fy_start),
            ('employee_id', 'in', employees.ids),
            ('state', 'not in', ('rejected', 'cancelled')),
        ])
        drafts = existing.filtered(lambda p: p.state == 'draft')
        new = self.create([{
            'employee_id': employee.id,
            'payout_type': 'annual',
            'fy_start': fy_start,
            'fy_end': fy_end,
            'period_end': fy_end,
        } for employee in employees - existing.employee_id])
        payouts = new | drafts
        payouts.action_compute()
        return payouts

    @api.model
    def _cron_generate_annual_payouts(self):
        """Create the draft annual payouts a configured number of days after the financial year closes."""
        delay = int(self._get_param('auto_generate_days', 0))
        if delay <= 0:
            return
        today = fields.Date.context_today(self)
        fy_start, _fy_end = self._get_fy_bounds(today)
        closed_start = fy_start - relativedelta(years=1)
        if today < fy_start + timedelta(days=delay) or \
                self._get_param('last_auto_generated_fy', '') == fields.Date.to_string(closed_start):
            return
        payouts = self._generate_annual_payouts(closed_start, fy_start - timedelta(days=1))
        self.env['ir.config_parameter'].sudo().set_param(
            PARAM_PREFIX + 'last_auto_generated_fy', fields.Date.to_string(closed_start))
        _logger.info("Equitable Benefit: generated %s draft payouts for the year starting %s",
                     len(payouts), closed_start)

    # ------------------------------------------------------------------
    # Separation (Full & Final Settlement)
    # ------------------------------------------------------------------
    @api.model
    def _create_fnf_payout(self, employee, last_day, resignation=False):
        """Settle the benefit of a separating employee in the Full & Final Settlement.

        Covers the current financial year pro-rata up to the last working day, and the
        previous year when its annual payout has not been paid yet. Returns the current
        year's payout (empty when no approved assignment falls in it).
        """
        fy_start, fy_end = self._get_fy_bounds(last_day)
        previous_end = fy_start - timedelta(days=1)
        settlement = {'separation_date': last_day, 'resignation_id': resignation and resignation.id or False}
        previous = self._settle_year(
            employee, fy_start - relativedelta(years=1), previous_end, 'annual', previous_end, settlement)
        current = self._settle_year(employee, fy_start, fy_end, 'fnf', last_day, settlement)
        (previous | current)._eb_notify_group(
            'bxi_equitable_benefit.group_eb_revenue_assurance',
            _("Review the Full & Final equitable benefit of %s", employee.name))
        return current

    @api.model
    def _settle_year(self, employee, fy_start, fy_end, payout_type, period_end, settlement):
        """Create, recompute or re-date one year's payout of a separating employee."""
        if not self.env['bxi.eb.assignment'].search_count([
            ('employee_id', '=', employee.id),
            ('state', '=', 'approved'),
            ('date_from', '<=', period_end),
            '|', ('date_to', '=', False), ('date_to', '>=', fy_start),
        ], limit=1):
            return self.browse()
        payout = self.search([
            ('employee_id', '=', employee.id),
            ('fy_start', '=', fy_start),
            ('state', 'not in', ('rejected', 'cancelled')),
        ], limit=1)
        if not payout:
            payout = self.create(dict(settlement, employee_id=employee.id, payout_type=payout_type,
                                      fy_start=fy_start, fy_end=fy_end, period_end=period_end))
            payout._compute_payout()
        elif payout.state == 'draft':
            payout.write(dict(settlement, payout_type=payout_type, period_end=period_end))
            payout._compute_payout()
        elif payout.state in ('validated', 'approved') and not payout.payslip_id:
            last_day = settlement['separation_date']
            payout.separation_date = last_day
            if payout.payout_date and payout.payout_date > last_day:
                payout.payout_date = last_day
            payout.message_post(body=_(
                "%(employee)s separates on %(day)s: settle this payout in the Full & Final Settlement. "
                "Reset it to draft and recompute if the eligibility period must change.",
                employee=employee.name, day=last_day))
        else:
            return self.browse()
        return payout


class BxiEbPayoutLine(models.Model):
    _name = 'bxi.eb.payout.line'
    _description = 'Equitable Benefit Payout Line'
    _order = 'date_from'

    payout_id = fields.Many2one('bxi.eb.payout', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='payout_id.currency_id')
    assignment_id = fields.Many2one('bxi.eb.assignment', readonly=True)
    work_pattern_id = fields.Many2one('bxi.eb.work.pattern', readonly=True)
    rate_id = fields.Many2one('bxi.eb.rate', readonly=True)
    date_from = fields.Date(readonly=True)
    date_to = fields.Date(readonly=True)
    days = fields.Integer(readonly=True)
    unpaid_days = fields.Float(string='Unpaid Leave Days', readonly=True)
    fraction = fields.Float(string='Share of Year', digits=(16, 6), readonly=True)
    component_a = fields.Monetary(string='Annual Component A', readonly=True)
    rate_percent = fields.Float(string='Rate (%)', digits=(16, 4), readonly=True)
    amount = fields.Monetary(readonly=True)
    compliance_checked = fields.Boolean(readonly=True)
    expected_days = fields.Float(string='Expected Office Days', digits=(16, 1), readonly=True)
    attended_days = fields.Float(string='Attended Office Days', digits=(16, 1), readonly=True)
    compliance_percent = fields.Float(
        string='Pattern Compliance (%)', digits=(16, 1), readonly=True,
        help="Office days attended against the days the work pattern expects, net of leave and public holidays.")
