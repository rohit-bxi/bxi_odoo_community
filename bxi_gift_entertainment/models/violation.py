from odoo import _, api, fields, models
from odoo.exceptions import UserError

DISCIPLINARY_OUTCOMES = ('reprimand', 'probation', 'suspension', 'termination')


class BxiGiftViolation(models.Model):
    """Suspected breach of the Gift and Entertainment Policy, investigated by LSO / the Ethics Committee."""
    _name = 'bxi.gift.violation'
    _description = 'Gift Policy Violation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    violation_type = fields.Selection([
        ('improper_receipt', 'Gift Received in Breach of the Policy'),
        ('solicitation', 'Solicitation of Gifts'),
        ('improper_gift', 'Improper Gift / Entertainment Given'),
        ('facilitating_payment', 'Facilitating Payment Requested or Made'),
        ('bribery', 'Suspected Bribery'),
        ('other', 'Other'),
    ], required=True, default='other', tracking=True)
    anonymous = fields.Boolean(readonly=True)
    reporter_user_id = fields.Many2one('res.users', string='Reported By', readonly=True,
                                       groups='bxi_gift_entertainment.group_gift_lso')
    description = fields.Text(required=True)
    subject_employee_id = fields.Many2one('hr.employee', string='Employee Concerned', tracking=True)
    subject_partner_id = fields.Many2one('res.partner', string='Third Party Concerned', tracking=True)
    related_ref = fields.Reference([
        ('bxi.gift.request', 'Gift Request'),
        ('bxi.gift.receipt', 'Receipt of Gift'),
        ('bxi.gift.donation', 'Donation'),
        ('bxi.gift.sponsorship', 'Sponsorship'),
    ], string='Related Record')
    investigation = fields.Html()
    outcome = fields.Selection([
        ('no_violation', 'No Violation'),
        ('reprimand', 'Reprimand / Warning Memo'),
        ('probation', 'Probation'),
        ('suspension', 'Suspension Order'),
        ('blacklisting', 'Blacklisting of the Third Party'),
        ('termination', 'Termination of Employment / Contract'),
        ('litigation', 'Litigation'),
        ('recovery', 'Recovery of Damages'),
    ], tracking=True)
    closed_date = fields.Date(readonly=True)
    state = fields.Selection([
        ('new', 'New'),
        ('investigating', 'Investigating'),
        ('closed', 'Closed'),
    ], default='new', required=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('bxi.gift.violation') or 'New'
        records = super().create(vals_list)
        for user in self.env.ref('bxi_gift_entertainment.group_gift_lso').sudo().all_user_ids.filtered(
                lambda u: u.active and not u.share):
            records.sudo().activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                             summary=_("Investigate the reported policy violation"))
        return records

    def _check_officer(self):
        if not self.env.user.has_group('bxi_gift_entertainment.group_gift_lso'):
            raise UserError(_("Only the LSO team can investigate violations."))

    def action_investigate(self):
        self._check_officer()
        self.filtered(lambda r: r.state == 'new').write({'state': 'investigating'})
        return True

    def action_close(self):
        self._check_officer()
        for rec in self:
            if not rec.outcome:
                raise UserError(_("Set the outcome before closing %s.", rec.name))
            rec.write({'state': 'closed', 'closed_date': fields.Date.context_today(rec)})
            if rec.outcome == 'blacklisting' and rec.subject_partner_id:
                rec.subject_partner_id.commercial_partner_id.sudo().write({
                    'gift_blacklisted': True,
                    'gift_blacklist_reason': _("Violation %s", rec.name),
                })
            if rec.outcome in DISCIPLINARY_OUTCOMES and rec.subject_employee_id \
                    and 'bxi.eb.disciplinary.action' in self.env:
                # Equitable Benefit eligibility: no active disciplinary action during the period.
                self.env['bxi.eb.disciplinary.action'].sudo().create({
                    'employee_id': rec.subject_employee_id.id,
                    'name': _("Gift Policy violation %s", rec.name),
                    'date_from': rec.closed_date,
                    'description': dict(rec._fields['outcome'].selection)[rec.outcome],
                })
            rec.sudo().activity_ids.action_feedback()
        return True


class BxiGiftViolationReportWizard(models.TransientModel):
    """Report a concern, named or anonymously: an anonymous report keeps no trace of the reporter."""
    _name = 'bxi.gift.violation.report.wizard'
    _description = 'Report a Gift Policy Concern'

    violation_type = fields.Selection(
        lambda self: self.env['bxi.gift.violation']._fields['violation_type'].selection,
        required=True, default='other')
    anonymous = fields.Boolean(string='Report Anonymously')
    description = fields.Text(required=True)
    subject_employee_id = fields.Many2one('hr.employee', string='Employee Concerned')
    subject_partner_id = fields.Many2one('res.partner', string='Third Party Concerned')

    def action_report(self):
        self.ensure_one()
        vals = {
            'violation_type': self.violation_type,
            'anonymous': self.anonymous,
            'description': self.description,
            'subject_employee_id': self.subject_employee_id.id,
            'subject_partner_id': self.subject_partner_id.id,
            'company_id': self.env.company.id,
        }
        Violation = self.env['bxi.gift.violation']
        if self.anonymous:
            # Created by the superuser so that neither the author nor the followers reveal the reporter.
            violation = Violation.with_user(self.env.ref('base.user_root')).with_context(
                mail_create_nosubscribe=True).sudo().create(vals)
        else:
            violation = Violation.sudo().create(dict(vals, reporter_user_id=self.env.user.id))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Concern reported"),
                'message': _("Reference %s. Retaliation against anyone reporting in good faith is prohibited.",
                             violation.name),
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
