# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import AccessError, UserError

CONTACT_EMAIL_PARAM = 'bxi_antitrust_compliance.contact_email'
DEFAULT_CONTACT_EMAIL = 'internalIT@bxitech.com'


class AntitrustMixin(models.AbstractModel):
    """Shared behaviour of compliance records: reference, owner, CPO notifications."""
    _name = 'antitrust.mixin'
    _description = 'Antitrust Compliance Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _sequence_code = False
    # Fields only the workflow (running as superuser) or the CPO may change.
    _workflow_fields = {'state', 'name', 'employee_id'}
    # States in which the employee may still edit the record.
    _editable_states = ('draft',)

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True,
                       default=lambda self: self.env._('New'))
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        index=True,
        default=lambda self: self.env.user.employee_id,
    )
    employee_user_id = fields.Many2one(related='employee_id.user_id', store=True, string='Employee User')
    company_id = fields.Many2one(related='employee_id.company_id', store=True, string='Company')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', self.env._('New')) == self.env._('New') and self._sequence_code:
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(self._sequence_code) or self.env._('New')
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and not self._is_cpo():
            if vals.keys() & self._workflow_fields:
                raise AccessError(self.env._("These fields are set by the compliance workflow."))
            if any(rec.state not in self._editable_states for rec in self):
                raise UserError(self.env._("This record has been submitted and can no longer be changed."))
        return super().write(vals)

    # ── Helpers ──────────────────────────────────────────────────────────
    @api.model
    def _is_cpo(self):
        return self.env.su or self.env.user.has_group('bxi_hr_policy.group_policy_cpo')

    @api.model
    def _cpo_users(self):
        return self.env.ref('bxi_hr_policy.group_policy_cpo').sudo().user_ids.filtered(
            lambda u: u.active and not u.share and u.id != self.env.ref('base.user_root').id)

    @api.model
    def _contact_email(self):
        return self.env['ir.config_parameter'].sudo().get_param(CONTACT_EMAIL_PARAM) or DEFAULT_CONTACT_EMAIL

    @api.model
    def _contact_partner(self):
        email = self._contact_email()
        Partner = self.env['res.partner'].sudo()
        partner = Partner.search([('email', '=ilike', email)], limit=1)
        return partner or Partner.create({'name': self.env._('Compliance (%(email)s)', email=email), 'email': email})

    def _check_owner_or_cpo(self):
        for rec in self:
            if not (self._is_cpo() or rec.employee_user_id == self.env.user):
                raise AccessError(self.env._("You are not allowed to do this on %(ref)s.", ref=rec.name))

    def _notify_cpo(self, summary, note='', urgent=False, email_contact=False):
        """To-do for every CPO member and, optionally, an email to the compliance mailbox."""
        deadline = fields.Date.context_today(self)
        for rec in self.sudo():
            for user in self._cpo_users():
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=deadline if urgent else None,
                    user_id=user.id,
                    summary=summary,
                    note=note,
                )
            if email_contact:
                rec.message_post(
                    body=note or summary,
                    subject=f"{'[URGENT] ' if urgent else ''}{summary}",
                    partner_ids=self._contact_partner().ids,
                    subtype_xmlid='mail.mt_comment',
                )

    def _notify_employee(self, body):
        for rec in self.sudo():
            partner = rec.employee_id.work_contact_id or rec.employee_user_id.partner_id
            rec.message_post(body=body, partner_ids=partner.ids, subtype_xmlid='mail.mt_comment')

    def _done_cpo_activities(self, feedback=False):
        self.sudo().activity_ids.filtered(lambda a: a.user_id in self._cpo_users()).action_feedback(feedback=feedback)
