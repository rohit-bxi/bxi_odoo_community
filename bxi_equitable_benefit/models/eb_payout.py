import calendar
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .eb_eligibility import RATING_ORDER

PARAM_PREFIX = 'bxi_equitable_benefit.'


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


class BxiEbPayout(models.Model):
    _name = 'bxi.eb.payout'
    _description = 'Equitable Benefit Payout'
    _inherit = ['mail.thread', 'mail.activity.mixin']
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
    fy_start = fields.Date(string='Financial Year Start', required=True)
    fy_end = fields.Date(string='Financial Year End', required=True)
    fy_name = fields.Char(string='Financial Year', compute='_compute_fy_name', store=True)
    period_end = fields.Date(
        string='Eligibility Period End', required=True,
        help="End of the financial year, or the last working day for a Full & Final Settlement.")
    resignation_id = fields.Many2one('employee.resignation', readonly=True)
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
    computed_date = fields.Datetime(readonly=True, copy=False)

    line_ids = fields.One2many('bxi.eb.payout.line', 'payout_id', string='Computation Lines', copy=False)
    amount_computed = fields.Monetary(readonly=True, tracking=True)

    # Exceptions (Governance: written approval by designated leadership)
    is_exception = fields.Boolean(string='Approved Exception', tracking=True)
    exception_amount = fields.Monetary(tracking=True)
    exception_reason = fields.Text()
    exception_approver_id = fields.Many2one('res.users', string='Approved By (Leadership)', tracking=True)
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
            if not rec.fy_start <= rec.period_end <= rec.fy_end:
                raise ValidationError(_("The eligibility period end must fall within the financial year."))

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

    # ------------------------------------------------------------------
    # Computation
    # ------------------------------------------------------------------
    def action_compute(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft payouts can be recomputed."))
            rec._compute_payout()

    def _leave_days(self, flag, date_from, date_to):
        leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'validate'),
            ('holiday_status_id.%s' % flag, '=', True),
            ('request_date_from', '<=', date_to),
            ('request_date_to', '>=', date_from),
        ])
        return leaves, sum(
            _overlap_days(l.request_date_from, l.request_date_to, date_from, date_to) for l in leaves)

    def _check_eligibility(self):
        """Return (eligible, reasons, values to write)."""
        self.ensure_one()
        reasons = []
        start, end = self.fy_start, self.period_end

        disciplinary = self.env['bxi.eb.disciplinary.action'].sudo()._overlapping(self.employee_id, start, end)
        if disciplinary:
            reasons.append(_("Disciplinary action during the eligibility period: %s",
                             ', '.join(disciplinary.mapped('name'))))

        rating = self.env['bxi.eb.performance.rating'].sudo().search([
            ('employee_id', '=', self.employee_id.id), ('fy_start', '=', self.fy_start)], limit=1)
        min_rating = self._get_param('min_rating', 'meets')
        if rating:
            if RATING_ORDER[rating.rating] < RATING_ORDER.get(min_rating, 1):
                reasons.append(_("Performance rating '%s' is below the required level.",
                                 dict(rating._fields['rating'].selection)[rating.rating]))
        elif not self._get_param('allow_missing_rating', False):
            reasons.append(_("No performance rating recorded for this financial year."))

        _leaves, unauthorized = self._leave_days('eb_is_unauthorized', start, end)
        max_unauthorized = float(self._get_param('max_unauthorized_days', 3))
        if unauthorized > max_unauthorized:
            reasons.append(_("Unauthorized absence of %(days)s days exceeds the allowed %(max)s days.",
                             days=unauthorized, max=max_unauthorized))

        _leaves, unpaid = self._leave_days('eb_is_unpaid', start, end)
        return not reasons, reasons, {
            'disciplinary_count': len(disciplinary),
            'rating': rating and dict(rating._fields['rating'].selection)[rating.rating] or False,
            'unauthorized_absence_days': unauthorized,
            'unpaid_leave_days': unpaid,
            'unpaid_leave_prorated': unpaid > float(self._get_param('unpaid_leave_threshold_days', 30)),
        }

    def _get_segments(self):
        """Split approved assignments into periods with a constant rate and Component A."""
        self.ensure_one()
        Rate = self.env['bxi.eb.rate'].sudo()
        employee = self.employee_id.sudo()
        assignments = self.env['bxi.eb.assignment'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'approved'),
            ('date_from', '<=', self.period_end),
            '|', ('date_to', '=', False), ('date_to', '>=', self.fy_start),
        ], order='date_from')
        version_dates = set(employee.with_context(active_test=False).version_ids.mapped('date_version'))
        segments = []
        for assignment in assignments:
            seg_from = max(assignment.date_from, self.fy_start)
            seg_to = min(assignment.date_to or self.period_end, self.period_end)
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
        eligible, reasons, values = self._check_eligibility()
        basis = self._get_param('proration_basis', 'months')
        fy_days = (self.fy_end - self.fy_start).days + 1
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
            line_vals.append((0, 0, {
                'assignment_id': seg['assignment'].id,
                'work_pattern_id': seg['assignment'].work_pattern_id.id,
                'rate_id': seg['rate'].id,
                'date_from': seg['date_from'],
                'date_to': seg['date_to'],
                'days': days,
                'unpaid_days': unpaid,
                'fraction': fraction,
                'component_a': seg['component_a'],
                'rate_percent': rate_percent,
                'amount': self.currency_id.round(seg['component_a'] * rate_percent / 100 * fraction),
            }))
        if not line_vals:
            reasons.append(_("No approved work pattern assignment in the eligibility period."))
            eligible = False
        self.line_ids.unlink()
        values.update({
            'line_ids': line_vals,
            'is_eligible': eligible,
            'ineligibility_reason': '\n'.join(reasons) or False,
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
            if rec.is_exception and not (rec.exception_reason and rec.exception_approver_id
                                         and rec.exception_attachment_ids):
                raise UserError(_("An exception needs a reason, the approving leader and "
                                  "the written approval attached."))
        self.write({'state': 'validated', 'validated_by_id': self.env.user.id})

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

    def action_cancel(self):
        if any(rec.state == 'paid' or rec.payslip_id for rec in self):
            raise UserError(_("Payouts already included in a payslip cannot be cancelled."))
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        if any(rec.state == 'paid' or rec.payslip_id for rec in self):
            raise UserError(_("Payouts already included in a payslip cannot be reset."))
        self.write({'state': 'draft', 'validated_by_id': False, 'approved_by_id': False})

    def _default_payout_date(self):
        self.ensure_one()
        return self.period_end if self.payout_type == 'fnf' else self.fy_end + timedelta(days=1)

    @api.model
    def _create_fnf_payout(self, employee, last_day, resignation=False):
        fy_start, fy_end = self._get_fy_bounds(last_day)
        existing = self.search([
            ('employee_id', '=', employee.id),
            ('fy_start', '=', fy_start),
            ('state', 'not in', ('rejected', 'cancelled')),
        ], limit=1)
        if existing:
            if existing.state == 'draft':
                existing.write({'payout_type': 'fnf', 'period_end': last_day,
                                'resignation_id': resignation and resignation.id})
                existing._compute_payout()
            return existing
        payout = self.create({
            'employee_id': employee.id,
            'payout_type': 'fnf',
            'fy_start': fy_start,
            'fy_end': fy_end,
            'period_end': last_day,
            'resignation_id': resignation and resignation.id,
        })
        payout._compute_payout()
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
