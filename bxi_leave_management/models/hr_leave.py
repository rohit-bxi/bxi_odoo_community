from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date


class HrEmployeeLeave(models.Model):
    _inherit = 'hr.leave'

    is_submission_email_sent = fields.Boolean(
        string="Submission Email Sent",
        default=False,
        copy=False
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._check_and_send_leave_notification()
        return records

    def write(self, vals):
        res = super().write(vals)
        for rec in self:
            rec._check_and_send_leave_notification()
        return res

    def action_confirm(self):
        res = super().action_confirm()
        for rec in self:
            rec._check_and_send_leave_notification()
        return res

    def _check_and_send_leave_notification(self):
        for rec in self:
            if rec.is_submission_email_sent:
                continue
            if rec.state not in ('draft', 'cancel', 'refuse'):
                rec._send_leave_submission_email()

    def _send_leave_submission_email(self):
        template = self.env.ref(
            'bxi_leave_management.email_template_leave_request_submitted',
            raise_if_not_found=False
        )
        if not template:
            return
        for rec in self:
            if rec.is_submission_email_sent:
                continue

            recipients = ['hr@bxitech.com']

            manager = rec.employee_id.parent_id or rec.employee_id.leave_manager_id
            manager_email = False
            if manager:
                manager_email = manager.work_email or (manager.user_id and manager.user_id.email)

            if manager_email:
                recipients.append(manager_email.strip())

            unique_recipients = list(dict.fromkeys([r for r in recipients if r]))
            email_to_str = ','.join(unique_recipients)

            rec.sudo().write({'is_submission_email_sent': True})

            template.sudo().send_mail(
                rec.id,
                email_values={'email_to': email_to_str},
                force_send=True
            )

    @api.constrains('holiday_status_id', 'request_date_from', 'request_date_to')
    def _check_rh_leave_rules(self):
        for rec in self:

            # Apply only for RH
            if not rec.holiday_status_id or rec.holiday_status_id.time_off_code != 'RH':
                continue

            # =========================
            # RULE 1: ONLY 1 DAY
            # =========================
            if rec.request_date_from != rec.request_date_to:
                raise ValidationError("RH leave can only be applied for 1 day.")

            # =========================
            # RULE 2: ONLY OPTIONAL HOLIDAY DATE
            # =========================
            optional_holiday = self.env['l10n.in.hr.leave.optional.holiday'].search([
                ('date', '=', rec.request_date_from),
                ('company_id', '=', rec.company_id.id)
            ], limit=1)

            if not optional_holiday:
                raise ValidationError(
                    "RH leave can only be applied on Optional Holiday dates."
                )

            # =========================
            # RULE 3: ADVANCE NOTICE (RH)
            # RH must be applied at least 3 days before the leave date.
            # =========================
            if rec.request_date_from:
                try:
                    days_diff = (rec.request_date_from - date.today()).days
                    if days_diff < 3:
                        raise ValidationError(
                            "RH leave must be applied at least 3 days before the leave date."
                        )
                except TypeError:
                    # If dates are invalid or None, let other validations handle it
                    pass

    @api.constrains('holiday_status_id', 'request_date_from', 'request_date_to')
    def _check_el_leave_rules(self):
        """
        Enforce EL (Earned Leave) application window: must be applied at least 7 days before.
        This runs in addition to any other constraints.
        """
        for rec in self:
            if not rec.holiday_status_id or rec.holiday_status_id.time_off_code != 'EL':
                continue

            if rec.request_date_from:
                try:
                    days_diff = (rec.request_date_from - date.today()).days
                    if days_diff < 7:
                        raise ValidationError(
                            "EL leave must be applied at least 7 days before the leave start date."
                        )
                except TypeError:
                    pass