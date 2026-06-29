from odoo import models, fields, api, _
import re


class HelpdeskTicket(models.Model):
    _inherit = 'helpdesk.ticket'

    category_id = fields.Many2one(
        'helpdesk.category',
        string='Category'
    )
    sub_category_id = fields.Many2one(
        'helpdesk.sub.category',
        string='Sub Category'
    )

    escalation_level_id = fields.Many2one(
        "helpdesk.escalation.level",
        string="Escalation Level",
        domain="[('team_id', '=', team_id)]"
    )

    escalation_assignee_ids = fields.Many2many(
        related="escalation_level_id.assignees_ids",
        string="Escalation Assignees"
    )

    child_ticket_ids = fields.Many2many(
        'helpdesk.ticket',
        'helpdesk_ticket_child_rel',
        'parent_id',
        'child_id',
        string='Child Ticket'
    )

    additional_resolution_owner = fields.Many2one(
        'hr.employee',
        string='Additional Resolution Owner'
    )

    assigned_resolved_by = fields.Many2one(
        'hr.employee',
        string='Assigned To/Resolved By'
    )

    def _get_team_alias_email(self):
        self.ensure_one()
        alias = self.team_id.alias_id
        if alias and alias.alias_name and alias.alias_domain:
            return f"{alias.alias_name}@{alias.alias_domain}"
        return False

    def message_post(self, **kwargs):
        """
        Requirement:
        - Outgoing email should be sent FROM the helpdesk team's alias email
        - Chatter author/name should remain the logged-in user
        """

        # Keep multi-record safety
        if len(self) != 1:
            results = []
            for rec in self:
                results.append(super(HelpdeskTicket, rec).message_post(**kwargs))
            return results[-1] if results else False

        message_type = kwargs.get("message_type", "comment")
        subtype_xmlid = kwargs.get("subtype_xmlid")
        partner_ids = kwargs.get("partner_ids") or []

        # "Send message" in chatter -> comment + not internal note + has recipients
        is_send_message = (
            message_type == "comment"
            and subtype_xmlid != "mail.mt_note"
            and bool(partner_ids)
        )

        if is_send_message:
            kwargs = dict(kwargs)  # make a mutable copy

            # ✅ Keep chatter author as actual user
            kwargs["author_id"] = self.env.user.partner_id.id

            # ✅ Force outgoing From email as team alias
            alias_email = self._get_team_alias_email()
            if alias_email:
                kwargs["email_from"] = f"{self.team_id.name} <{alias_email}>"

        return super().message_post(**kwargs)

    def _notify_get_reply_to(self, default=None, author_id=None, **kwargs):
        """
        Make replies go to the team's alias email.
        Odoo 19 passes author_id; keep signature compatible using **kwargs.
        """
        res = super()._notify_get_reply_to(default=default, author_id=author_id, **kwargs)
        for ticket in self:
            alias_email = ticket._get_team_alias_email()
            if alias_email:
                res[ticket.id] = alias_email
        return res

    # @api.model
    # def message_new(self, msg_dict, custom_values=None):
    #     subject = msg_dict.get("subject", "") or ""
    #     body = msg_dict.get("body", "") or ""
    #     content = subject + " " + body
    #
    #     ticket_pattern = r"""
    #     (?i)
    #     (
    #         TKT[-\s]*\d+ |
    #         TICKET\s*(NO\.?|NUMBER)?\s*[:\-]?\s*\d+ |
    #         TICKET\s+\d+ |
    #         \b\d{3,7}\b
    #     )
    #     """
    #
    #     match = re.search(ticket_pattern, content, re.VERBOSE)
    #
    #     if match:
    #         raw_ref = match.group(0)
    #
    #         number = re.findall(r"\d+", raw_ref)[0]
    #         ticket = self.search([
    #             ("name", "ilike", number)
    #         ], limit=1)
    #
    #         if ticket:
    #             ticket.message_post(
    #                 body=body,
    #                 subject=subject,
    #                 message_type="email",
    #                 subtype_xmlid="mail.mt_comment",
    #             )
    #             return ticket
    #
    #     return super().message_new(msg_dict, custom_values)
