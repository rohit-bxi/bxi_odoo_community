from odoo import Command, api, models
from odoo.exceptions import UserError

PARAM_PREFIX = 'bxi_training_policy.'
HR_GROUP = 'bxi_training_policy.group_training_hr'
ES_GROUP = 'bxi_training_policy.group_training_es'
FINANCE_GROUP = 'bxi_training_policy.group_training_finance'
ADMIN_GROUP = 'bxi_training_policy.group_training_admin'


class BxiTrainingMixin(models.AbstractModel):
    """Helpers shared by the Training Policy records: parameters, notifications and entries."""
    _name = 'bxi.training.mixin'
    _description = 'Training Policy Helpers'

    # ── Parameters ───────────────────────────────────────────────────────
    @api.model
    def _get_param(self, key, default):
        value = self.env['ir.config_parameter'].sudo().get_param(PARAM_PREFIX + key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @api.model
    def _get_agreement_threshold(self):
        return self._get_param('agreement_threshold', 30000)

    # ── Notifications ────────────────────────────────────────────────────
    def _notify_user(self, user, summary, note=''):
        """Create a to-do activity for a user (which also emails them)."""
        self.ensure_one()
        if user and not user.share:
            self.sudo().activity_schedule('mail.mail_activity_data_todo', user_id=user.id, summary=summary, note=note)

    def _get_group_users(self, group_xmlid):
        self.ensure_one()
        return self.env.ref(group_xmlid).sudo().all_user_ids.filtered(
            lambda user: self.company_id in user.company_ids and not user.share)

    def _notify_group(self, responsible, group_xmlid, summary, note=''):
        """Notify the company's responsible user, or every member of the group in the company."""
        self.ensure_one()
        for user in responsible or self._get_group_users(group_xmlid):
            self._notify_user(user, summary, note)

    def _notify_employee(self, body, attachment_ids=None):
        self.ensure_one()
        employee = self.employee_id.sudo()
        partner = employee.work_contact_id or employee.user_id.partner_id
        self.sudo().message_post(
            body=body, partner_ids=partner.ids, subtype_xmlid='mail.mt_comment',
            attachment_ids=attachment_ids or [])

    def _close_activities(self, feedback=False):
        self.sudo().activity_ids.filtered(lambda act: act.user_id == self.env.user).action_feedback(feedback=feedback)

    # ── Accounting ───────────────────────────────────────────────────────
    def _get_employee_partner(self):
        self.ensure_one()
        employee = self.employee_id.sudo()
        partner = employee.work_contact_id or employee.user_id.partner_id
        if not partner:
            raise UserError(self.env._("%(employee)s has no contact to post the entry on.", employee=employee.name))
        return partner

    def _post_entry(self, journal, date, label, debit_account, credit_account, amount, partner=False,
                    debit_partner=None, credit_partner=None):
        """Post a two-line journal entry; users of the policy need no accounting rights."""
        self.ensure_one()
        partner = partner or self._get_employee_partner()
        debit_partner = partner if debit_partner is None else debit_partner
        credit_partner = partner if credit_partner is None else credit_partner
        move = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': date,
            'ref': label,
            'company_id': self.company_id.id,
            'line_ids': [
                Command.create({
                    'name': label, 'account_id': debit_account.id,
                    'partner_id': debit_partner.id if debit_partner else False,
                    'debit': amount, 'credit': 0.0,
                }),
                Command.create({
                    'name': label, 'account_id': credit_account.id,
                    'partner_id': credit_partner.id if credit_partner else False,
                    'debit': 0.0, 'credit': amount,
                }),
            ],
        })
        move.action_post()
        return move

    def _get_cost_credit_account(self):
        """Account the training cost sits on while the service period runs."""
        self.ensure_one()
        company = self.company_id
        if company.trn_accounting_mode == 'bonded':
            return company.trn_bonded_account_id
        return company.trn_expense_account_id
