import base64
import logging

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _, Command
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class BxiServiceAgreementTier(models.Model):
    """Annexure A: minimum service period by reimbursed amount."""
    _name = 'bxi.service.agreement.tier'
    _description = 'Service Agreement Tier'
    _order = 'min_amount'
    _rec_name = 'months'

    min_amount = fields.Float(string='From Amount', required=True)
    max_amount = fields.Float(string='To Amount', help="0 means no upper limit.")
    months = fields.Integer(string='Service Period (Months)', required=True)

    @api.constrains('min_amount', 'max_amount', 'months')
    def _check_amounts(self):
        for tier in self:
            if tier.months <= 0:
                raise ValidationError(_("The service period must be at least one month."))
            if tier.max_amount and tier.max_amount < tier.min_amount:
                raise ValidationError(_("The upper amount must be greater than the lower amount."))

    @api.model
    def _get_months(self, amount):
        """Return the service period in months for an amount, or 0 if no agreement is needed."""
        for tier in self.sudo().search([], order='min_amount desc'):
            if amount >= tier.min_amount and (not tier.max_amount or amount <= tier.max_amount):
                return tier.months
        return 0

    @api.model
    def _get_min_amount(self):
        tier = self.sudo().search([], order='min_amount', limit=1)
        return tier.min_amount


class BxiServiceAgreement(models.Model):
    _name = 'bxi.service.agreement'
    _description = 'Certification Service Agreement'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_date desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    request_id = fields.Many2one('bxi.certification.request', string='Certification Request', readonly=True)
    voucher_id = fields.Many2one('bxi.certification.voucher', string='Voucher', readonly=True)
    certification_label = fields.Char(string='Certification', compute='_compute_certification_label')
    amount = fields.Monetary(string='Amount', currency_field='currency_id', required=True, tracking=True)
    start_date = fields.Date(
        string='Start Date',
        required=True,
        tracking=True,
        help="Date of clearing the certification exam.",
    )
    period_months = fields.Integer(string='Service Period (Months)', required=True, tracking=True)
    end_date = fields.Date(string='End Date', compute='_compute_end_date', store=True)
    sign_request_id = fields.Many2one('sign.request', string='Signature Request', readonly=True, copy=False)
    signed_date = fields.Date(string='Signed On', readonly=True, copy=False)
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('sent', 'Sent for Signature'),
            ('active', 'Active'),
            ('completed', 'Completed'),
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
    notes = fields.Text(string='Notes')

    @api.depends('request_id', 'voucher_id')
    def _compute_certification_label(self):
        for rec in self:
            if rec.request_id:
                rec.certification_label = rec.request_id._get_certification_label()
            else:
                rec.certification_label = rec.voucher_id.certification_id.display_name or ''

    @api.depends('start_date', 'period_months')
    def _compute_end_date(self):
        for rec in self:
            if rec.start_date and rec.period_months:
                rec.end_date = rec.start_date + relativedelta(months=rec.period_months)
            else:
                rec.end_date = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.service.agreement') or _('New')
        return super().create(vals_list)

    # ── Signature ────────────────────────────────────────────────────────
    def _get_signer_partner(self):
        self.ensure_one()
        employee = self.employee_id.sudo()
        partner = employee.work_contact_id or employee.user_id.partner_id
        if not partner or not partner.email:
            raise UserError(_("%(employee)s has no work email to receive the agreement.", employee=employee.name))
        return partner

    def action_send_for_signature(self):
        for rec in self:
            if rec.state not in ('draft', 'sent'):
                raise UserError(_("Only draft agreements can be sent for signature."))
            partner = rec._get_signer_partner()
            report = self.env.ref('bxi_certification_reimbursement.action_report_service_agreement')
            pdf, report_type = self.env['ir.actions.report'].sudo()._render_qweb_pdf(report, rec.ids)
            if report_type != 'pdf':
                raise UserError(_("The service agreement could not be rendered as a PDF."))
            SignTemplate = self.env['sign.template'].sudo()
            template_info = SignTemplate.create_from_attachment_data([{
                'name': f"{rec.name}.pdf",
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
            sign_request = self.env['sign.request'].sudo().create({
                'template_id': template.id,
                'reference': _("Service Agreement %(name)s", name=rec.name),
                'reference_doc': f"{rec._name},{rec.id}",
                'subject': _("Certification Service Agreement to sign"),
                'request_item_ids': [Command.create({
                    'partner_id': partner.id,
                    'role_id': role.id,
                })],
            })
            rec.write({'sign_request_id': sign_request.id, 'state': 'sent'})

    def _get_portal_sign_url(self):
        self.ensure_one()
        item = self.sudo().sign_request_id.request_item_ids[:1]
        if self.state != 'sent' or not item:
            return False
        return f'/sign/document/{item.sign_request_id.id}/{item.access_token}?portal=1'

    def _try_send_for_signature(self):
        """Send for signature without blocking the approval if it fails."""
        for rec in self:
            try:
                with self.env.cr.savepoint():
                    rec.action_send_for_signature()
            except Exception as error:  # noqa: BLE001 - HR can send it manually
                # Resolve lazy translated messages here, where the env gives the language.
                message = str(error)
                _logger.warning("Could not send service agreement %s for signature: %s", rec.name, message)
                rec.message_post(body=_(
                    "The agreement could not be sent for signature automatically (%(error)s). "
                    "Please send it manually or record a signed paper copy.",
                    error=message,
                ))
                managers = self.env.ref('bxi_certification_reimbursement.group_certification_manager').user_ids
                for user in managers[:5]:
                    rec.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=user.id,
                        summary=_("Send service agreement %(name)s", name=rec.name),
                    )

    def action_mark_signed(self):
        """Record a signed (paper) copy without the electronic signature."""
        for rec in self:
            if rec.state not in ('draft', 'sent'):
                raise UserError(_("Only agreements waiting for signature can be marked as signed."))
            if rec.sign_request_id.state in ('sent', 'shared'):
                rec.sign_request_id.sudo().cancel()
        self._on_signed()

    def _on_signed(self):
        for rec in self.filtered(lambda r: r.state in ('draft', 'sent')):
            rec.write({'state': 'active', 'signed_date': fields.Date.context_today(rec)})
            if rec.request_id.state == 'agreement_pending':
                rec.request_id._move_to_finance()

    def action_mark_recovered(self):
        for rec in self:
            if rec.state != 'active':
                raise UserError(_("Only active agreements can be recovered."))
        self.write({'state': 'recovered'})

    def action_waive(self):
        for rec in self:
            if rec.state != 'active':
                raise UserError(_("Only active agreements can be waived."))
        self.write({'state': 'waived'})

    def action_cancel(self):
        for rec in self:
            if rec.state not in ('draft', 'sent'):
                raise UserError(_("Only agreements not yet signed can be cancelled."))
            if rec.sign_request_id.state in ('sent', 'shared'):
                rec.sign_request_id.sudo().cancel()
        self.write({'state': 'cancelled'})

    def action_open_sign_request(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sign.request',
            'view_mode': 'form',
            'res_id': self.sign_request_id.id,
        }

    @api.model
    def _cron_complete_agreements(self):
        today = fields.Date.context_today(self)
        self.search([('state', '=', 'active'), ('end_date', '<', today)]).write({'state': 'completed'})

    def _is_due_on(self, date):
        """Whether the employee still owes the amount when leaving on ``date``."""
        self.ensure_one()
        return self.state == 'active' and (not date or not self.end_date or self.end_date > date)
