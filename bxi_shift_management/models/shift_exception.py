# -*- coding: utf-8 -*-

import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


class BxiShiftException(models.Model):
    _name = "bxi.shift.exception"
    _description = "Exception Working Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        readonly=True,
        default="New",
        tracking=True,
    )

    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,
        default=lambda self: self._default_employee_id(),
        tracking=True,
    )

    manager_id = fields.Many2one(
        "hr.employee",
        string="Manager",
        tracking=True,
    )

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        tracking=True,
    )

    date_from = fields.Date(
        string="From Date",
        required=True,
        tracking=True,
    )

    date_to = fields.Date(
        string="To Date",
        required=True,
        tracking=True,
    )

    to_location_id = fields.Many2one(
        "hr.work.location",
        string="To Work Location",
    )

    new_calendar_id = fields.Many2one(
        "resource.calendar",
        string="New Working Schedule",
    )

    allowed_weekdays = fields.Char(
        string="Allowed Weekdays",
        help="Comma-separated weekday numbers (0=Monday, 1=Tuesday, ..., 6=Sunday).",
    )

    mode = fields.Selection(
        [
            ("office", "Office"),
            ("home", "Home"),
            ("hybrid", "Hybrid"),
        ],
        string="Mode",
    )

    reason = fields.Text(
        string="Reason / Description",
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("manager_approval", "Manager Approval"),
            ("approved", "Approved"),
            ("refused", "Refused"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
        copy=False,
    )

    manager_remark = fields.Text(
        string="Manager Remark",
        tracking=True,
    )

    manager_approved_by = fields.Many2one(
        "hr.employee",
        string="Manager Approved By",
        readonly=True,
        copy=False,
        tracking=True,
    )

    manager_approved_date = fields.Datetime(
        string="Manager Approved On",
        readonly=True,
        copy=False,
        tracking=True,
    )

    # -------------------------------------------------------------------------
    # DEFAULTS
    # -------------------------------------------------------------------------

    @api.model
    def _default_employee_id(self):
        employee = self.env["hr.employee"].search(
            [
                ("user_id", "=", self.env.user.id),
            ],
            limit=1,
        )
        return employee.id or False

    # -------------------------------------------------------------------------
    # ONCHANGE
    # -------------------------------------------------------------------------

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        for record in self:
            if record.employee_id:
                record.manager_id = record.employee_id.parent_id or False
                record.company_id = (
                    record.employee_id.company_id or self.env.company
                )

    # -------------------------------------------------------------------------
    # CREATE
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """
        Odoo 19 create() receives a list of dictionaries.
        """

        for vals in vals_list:
            vals.setdefault(
                "name",
                self.env["ir.sequence"].sudo().next_by_code(
                    "bxi.shift.exception"
                )
                or "/",
            )

            # Automatically set manager from employee
            employee_id = vals.get("employee_id")

            if employee_id:
                employee = self.env["hr.employee"].browse(employee_id).exists()

                if employee:
                    vals.setdefault("manager_id", employee.parent_id.id or False)
                    vals.setdefault(
                        "company_id",
                        employee.company_id.id or self.env.company.id,
                    )

        records = super().create(vals_list)

        return records

    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for record in self:
            if (
                record.date_from
                and record.date_to
                and record.date_to < record.date_from
            ):
                raise UserError(
                    _("To Date cannot be earlier than From Date.")
                )

    # -------------------------------------------------------------------------
    # SUBMIT
    # -------------------------------------------------------------------------

    def action_submit(self):
        for record in self:

            if not record.employee_id:
                raise UserError(_("Employee is required."))

            if not record.manager_id:
                raise UserError(
                    _("The employee does not have a manager configured.")
                )

            if not record.date_from or not record.date_to:
                raise UserError(
                    _("From Date and To Date are required.")
                )

            if record.state != "draft":
                continue

            record.state = "manager_approval"

            manager_email = (
                record.manager_id.user_id.email
                if record.manager_id.user_id
                else False
            )

            if manager_email:
                try:
                    subject = _(
                        "Exception Working Request: %s"
                    ) % record.name

                    body = _(
                        "<p>Employee <strong>%s</strong> has requested "
                        "an exception working change from <strong>%s</strong> "
                        "to <strong>%s</strong>.</p>"
                        "<p><strong>Reason:</strong> %s</p>"
                    ) % (
                        record.employee_id.name,
                        record.date_from or "",
                        record.date_to or "",
                        record.reason or "",
                    )

                    self.env["mail.mail"].sudo().create(
                        {
                            "subject": subject,
                            "body_html": body,
                            "email_from": "hrsupport@bxitech.com",
                            "email_to": manager_email,
                            "auto_delete": True,
                        }
                    ).send()

                except Exception:
                    _logger.exception(
                        "Failed to send manager notification for shift exception %s",
                        record.name,
                    )

        return True

    # -------------------------------------------------------------------------
    # MANAGER APPROVE
    # -------------------------------------------------------------------------

    def action_manager_approve(self):
        current_employee = self.env["hr.employee"].search(
            [
                ("user_id", "=", self.env.user.id),
            ],
            limit=1,
        )
        for record in self:
            if record.state != "manager_approval":
                raise UserError(
                    _(
                        "Only requests in Manager Approval state "
                        "can be approved."
                    )
                )
            if (
                not current_employee
                or record.manager_id.id != current_employee.id
            ):
                raise UserError(
                    _(
                        "Only the employee's direct manager can approve "
                        "this request."
                    )
                )

            record.write(
                {
                    "state": "approved",
                    "manager_approved_by": current_employee.id,
                    "manager_approved_date": fields.Datetime.now(),
                }
            )

            # -------------------------------------------------------------
            # Notify employee
            # -------------------------------------------------------------

            employee_email = (
                record.employee_id.user_id.email
                if record.employee_id.user_id
                else record.employee_id.work_email
            )

            if employee_email:
                try:
                    subject = _(
                        "Your Exception Working Request Approved: %s"
                    ) % record.name

                    body = _(
                        "<p>Your exception working request from "
                        "<strong>%s</strong> to <strong>%s</strong> "
                        "has been approved by <strong>%s</strong>.</p>"
                    ) % (
                        record.date_from or "",
                        record.date_to or "",
                        self.env.user.name,
                    )

                    self.env["mail.mail"].sudo().create(
                        {
                            "subject": subject,
                            "body_html": body,
                            "email_from": "hrsupport@bxitech.com",
                            "email_to": employee_email,
                            "auto_delete": True,
                        }
                    ).send()

                except Exception:
                    _logger.exception(
                        "Failed to send employee approval email for %s",
                        record.name,
                    )

        return True
    # -------------------------------------------------------------------------
    # REFUSE
    # -------------------------------------------------------------------------

    def action_refuse(self):
        for record in self:
            if record.state not in ("manager_approval", "draft"):
                continue

            record.state = "refused"

        return True

    # -------------------------------------------------------------------------
    # SET TO DRAFT
    # -------------------------------------------------------------------------

    def action_set_draft(self):
        for record in self:
            record.state = "draft"

            record.manager_approved_by = False
            record.manager_approved_date = False

        return True