from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


def _next_business_day(moment):
    moment += timedelta(days=1)
    while moment.weekday() >= 5:
        moment += timedelta(days=1)
    return moment


class BxiGiftExtortion(models.Model):
    """Extortion demand (health, safety, ransomware, illegitimate detention) and any payment made."""
    _name = 'bxi.gift.extortion'
    _description = 'Extortion Payment Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    employee_id = fields.Many2one('hr.employee', required=True, tracking=True,
                                  default=lambda self: self.env.user.employee_id)
    company_id = fields.Many2one(related='employee_id.company_id', store=True)
    demand_datetime = fields.Datetime(string='Demand Received', required=True, default=fields.Datetime.now)
    threat_type = fields.Selection([
        ('health_safety', 'Health or Safety'),
        ('ransomware', 'Ransomware Attack'),
        ('detention', 'Imminent Illegitimate Detention'),
        ('other', 'Other'),
    ], required=True, default='health_safety')
    demanded_by = fields.Char(required=True)
    description = fields.Text(required=True)
    reported_to_id = fields.Many2one('res.users', string='Reported To (L1 Head / MD)', tracking=True,
                                     default=lambda self: self._default_reported_to())
    report_deadline = fields.Datetime(compute='_compute_report_deadline', store=True)
    reported_datetime = fields.Datetime(readonly=True, copy=False)
    late_report = fields.Boolean(compute='_compute_late_report', store=True)
    impossibility_reason = fields.Text(
        string='Why It Could Not Be Reported in Time',
        help="Physical or technological impossibility of reporting within one business day.")
    payment_requested = fields.Boolean(string='Payment Needed')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    payment_amount = fields.Monetary(currency_field='currency_id')
    decision_user_id = fields.Many2one('res.users', string='E&TC Decision By', readonly=True, copy=False)
    decision_date = fields.Datetime(readonly=True, copy=False)
    payment_reference = fields.Char(copy=False)
    accounting_reference = fields.Char(string='Accounting Entry', copy=False,
                                       help="Extortion payments must be accurately recorded in BXI's books.")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('reported', 'Reported'),
        ('payment_approved', 'Payment Approved'),
        ('payment_refused', 'Payment Refused'),
        ('paid', 'Paid'),
        ('closed', 'Closed'),
    ], default='draft', required=True, tracking=True)

    @api.model
    def _default_reported_to(self):
        employee = self.env.user.employee_id.sudo()
        return employee.l1_head_id.user_id or employee.parent_id.user_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('bxi.gift.extortion') or 'New'
        return super().create(vals_list)

    @api.depends('demand_datetime')
    def _compute_report_deadline(self):
        for rec in self:
            rec.report_deadline = rec.demand_datetime and _next_business_day(rec.demand_datetime)

    @api.depends('reported_datetime', 'report_deadline', 'impossibility_reason')
    def _compute_late_report(self):
        for rec in self:
            rec.late_report = bool(rec.reported_datetime and rec.report_deadline
                                   and rec.reported_datetime > rec.report_deadline and not rec.impossibility_reason)

    def _notify(self, users, summary):
        for user in users:
            self.activity_schedule('mail.mail_activity_data_todo', user_id=user.id, summary=summary)

    def _group_users(self, xmlid):
        return self.env.ref('bxi_gift_entertainment.%s' % xmlid).sudo().all_user_ids.filtered(
            lambda u: u.active and not u.share)

    def action_report(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("%s is already reported.", rec.name))
            if not rec.reported_to_id:
                raise UserError(_("Select the L1 Head / MD the demand is reported to."))
            rec.sudo().write({'state': 'reported', 'reported_datetime': fields.Datetime.now()})
            summary = _("Extortion demand reported: %s", rec.name)
            rec.sudo()._notify(rec.reported_to_id | rec._group_users('group_gift_lso'), summary)
            if rec.payment_requested:
                rec.sudo()._notify(rec._group_users('group_gift_etc'), _("Decide on extortion payment %s", rec.name))
        return True

    def _check_etc(self):
        if not self.env.user.has_group('bxi_gift_entertainment.group_gift_etc'):
            raise UserError(_("Only E&TC / the Office of the General Counsel can decide on an extortion payment."))

    def action_approve_payment(self):
        self._check_etc()
        for rec in self:
            if rec.state != 'reported' or not rec.payment_requested:
                raise UserError(_("Only reported demands needing a payment can be approved."))
            rec.write({'state': 'payment_approved', 'decision_user_id': self.env.user.id,
                       'decision_date': fields.Datetime.now()})
        return True

    def action_refuse_payment(self):
        self._check_etc()
        self.filtered(lambda r: r.state == 'reported').write({
            'state': 'payment_refused', 'decision_user_id': self.env.user.id, 'decision_date': fields.Datetime.now()})
        return True

    def action_mark_paid(self):
        for rec in self:
            if rec.state != 'payment_approved':
                raise UserError(_("A payment can only be made after E&TC approval."))
            if not (rec.payment_amount and rec.payment_reference and rec.accounting_reference):
                raise UserError(_("Enter the amount, the payment reference and the accounting entry."))
            rec.sudo().state = 'paid'
        return True

    def action_close(self):
        if not self.env.user.has_group('bxi_gift_entertainment.group_gift_lso'):
            raise UserError(_("Only the LSO team can close an extortion report."))
        self.write({'state': 'closed'})
        return True

    @api.model
    def _cron_unreported_demands(self):
        now = fields.Datetime.now()
        for rec in self.sudo().search([('state', '=', 'draft'), ('report_deadline', '<', now)]):
            pending = rec.activity_ids.user_id
            rec._notify(rec._group_users('group_gift_lso') - pending,
                        _("Extortion demand %s not reported within one business day", rec.name))
