from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import AccessError, UserError


class BxiCertificationVoucher(models.Model):
    """Certification voucher provided by BXI Tech to an employee."""
    _name = 'bxi.certification.voucher'
    _description = 'Certification Voucher'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'deadline, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self.env._('New'),
    )
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    certification_id = fields.Many2one('bxi.certification', string='Certification', required=True, tracking=True)
    voucher_code = fields.Char(string='Voucher Code', groups='bxi_certification_reimbursement.group_certification_academy')
    cost = fields.Monetary(string='Voucher Cost', currency_field='currency_id', required=True, tracking=True)
    issue_date = fields.Date(string='Issued On', default=fields.Date.context_today, required=True)
    deadline = fields.Date(
        string='Complete By',
        required=True,
        tracking=True,
        help="The certification must be completed by this date, otherwise the voucher "
             "cost is recovered as per the service agreement.",
    )
    exam_clear_date = fields.Date(string='Exam Cleared On', tracking=True)
    certificate_attachment_ids = fields.Many2many(
        'ir.attachment',
        'bxi_cert_voucher_certificate_rel',
        'voucher_id',
        'attachment_id',
        string='Certificate',
    )
    service_agreement_id = fields.Many2one('bxi.service.agreement', string='Service Agreement', readonly=True)
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('issued', 'Issued'),
            ('used', 'Certification Completed'),
            ('expired', 'Expired - To Recover'),
            ('recovered', 'Recovered'),
            ('waived', 'Waived'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
        copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', self.env._('New')) == self.env._('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.certification.voucher') or self.env._('New')
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and not self.env.user.has_group('bxi_certification_reimbursement.group_certification_academy'):
            if vals.keys() - {'exam_clear_date', 'certificate_attachment_ids'}:
                raise AccessError(self.env._("Only the LoB Academy can change voucher details."))
        return super().write(vals)

    def action_issue(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(self.env._("Only draft vouchers can be issued."))
            if rec.deadline < rec.issue_date:
                raise UserError(self.env._("The deadline cannot be before the issue date."))
            rec.state = 'issued'
            partner = rec.employee_id.sudo().work_contact_id
            rec.message_post(
                body=self.env._("A voucher for %(cert)s has been issued to you. Complete the certification by %(date)s.",
                       cert=rec.certification_id.display_name, date=rec.deadline),
                partner_ids=partner.ids,
                subtype_xmlid='mail.mt_comment',
            )

    def action_mark_used(self):
        for rec in self:
            if rec.state not in ('issued', 'expired'):
                raise UserError(self.env._("Only issued vouchers can be marked as used."))
            if not rec.exam_clear_date or not rec.certificate_attachment_ids:
                raise UserError(self.env._("Enter the exam clearing date and attach the certificate."))
            vals = {'state': 'used'}
            months = self.env['bxi.service.agreement.tier']._get_months(rec.cost)
            if months and not rec.service_agreement_id:
                agreement = self.env['bxi.service.agreement'].sudo().create({
                    'employee_id': rec.employee_id.id,
                    'company_id': rec.company_id.id,
                    'voucher_id': rec.id,
                    'amount': rec.cost,
                    'start_date': rec.exam_clear_date,
                    'period_months': months,
                })
                vals['service_agreement_id'] = agreement.id
                agreement._try_send_for_signature()
            rec.sudo().write(vals)

    def action_mark_recovered(self):
        self.filtered(lambda r: r.state == 'expired').write({'state': 'recovered'})

    def action_waive(self):
        self.filtered(lambda r: r.state == 'expired').write({'state': 'waived'})

    def action_cancel(self):
        for rec in self:
            if rec.state not in ('draft', 'issued'):
                raise UserError(self.env._("Only draft or issued vouchers can be cancelled."))
        self.write({'state': 'cancelled'})

    @api.model
    def _cron_check_deadlines(self):
        today = fields.Date.context_today(self)
        expired = self.search([('state', '=', 'issued'), ('deadline', '<', today)])
        expired.write({'state': 'expired'})
        managers = self.env.ref('bxi_certification_reimbursement.group_certification_manager').user_ids
        for voucher in expired:
            voucher.message_post(body=self.env._("The certification was not completed by the deadline; the voucher cost must be recovered."))
            for user in managers[:5]:
                voucher.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=user.id,
                    summary=self.env._("Recover voucher cost from %(employee)s", employee=voucher.employee_id.name),
                )
        days = int(self.env['bxi.certification.request']._get_policy_param('voucher_reminder_days', 7))
        reminder_date = today + timedelta(days=days)
        for voucher in self.search([('state', '=', 'issued'), ('deadline', '=', reminder_date)]):
            partner = voucher.employee_id.sudo().work_contact_id
            voucher.message_post(
                body=self.env._("Reminder: complete %(cert)s by %(date)s, otherwise the voucher cost will be recovered.",
                       cert=voucher.certification_id.display_name, date=voucher.deadline),
                partner_ids=partner.ids,
                subtype_xmlid='mail.mt_comment',
            )
