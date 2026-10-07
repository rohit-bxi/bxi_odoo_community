from odoo import models


class BxiEbNotifyMixin(models.AbstractModel):
    """Activities for reviewers and chatter notifications for the employee."""
    _name = 'bxi.eb.notify.mixin'
    _description = 'Equitable Benefit Notifications'

    def _eb_notify_group(self, group_xmlid, summary, note=''):
        """Create a to-do activity for every internal member of the group in the record's company,
        unless they already have one open on the record."""
        todo = self.env.ref('mail.mail_activity_data_todo')
        for rec in self:
            pending = rec.sudo().activity_ids.filtered(lambda act: act.activity_type_id == todo).user_id
            users = self.env.ref(group_xmlid).sudo().all_user_ids.filtered(
                lambda user: user.active and not user.share
                and (not rec.company_id or rec.company_id in user.company_ids))
            for user in users - pending:
                rec.sudo().activity_schedule(
                    'mail.mail_activity_data_todo', user_id=user.id, summary=summary, note=note)

    def _eb_close_activities(self, feedback=False):
        self.sudo().activity_feedback(['mail.mail_activity_data_todo'], feedback=feedback)

    def _eb_notify_employee(self, body):
        for rec in self:
            employee = rec.employee_id.sudo()
            partner = employee.work_contact_id or employee.user_id.partner_id
            rec.sudo().message_post(body=body, partner_ids=partner.ids, subtype_xmlid='mail.mt_comment')
