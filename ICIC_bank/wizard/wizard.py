from odoo import _, fields, models
from odoo.exceptions import ValidationError

import logging

_logger = logging.getLogger(__name__)


class ICICIOtpWizard(models.TransientModel):
    _name = "icici.otp.wizard"
    _description = "ICICI OTP Verification Wizard"

    otp = fields.Char(
        string="OTP",
        required=True,
        copy=False,
    )

    payslip_ids = fields.Many2many(
        "hr.payslip",
        string="Payslips",
        required=True,
        readonly=True,
    )

    payment_date = fields.Date(
        string="Payment Date",
        required=True,
        default=fields.Date.today,
        copy=False,
    )

    def action_confirm_otp(self):
        """Submit Bulk Payment after OTP verification."""

        self.ensure_one()

        if not self.payslip_ids:
            raise ValidationError(
                _("No payslips selected.")
            )

        otp = (self.otp or "").strip()

        if not otp:
            raise ValidationError(
                _("Please enter the OTP.")
            )

        if not self.payment_date:
            raise ValidationError(
                _("Please select the Payment Date.")
            )

        # ------------------------------------------------------
        # Validate Payslips
        # ------------------------------------------------------

        for slip in self.payslip_ids:

            if slip.icici_payment_status != "otp_pending":
                raise ValidationError(
                    _(
                        "%s is not waiting for OTP confirmation."
                    )
                    % slip.employee_id.name
                )

            if not slip.icici_reference:
                raise ValidationError(
                    _(
                        "ICICI Reference is missing for %s."
                    )
                    % slip.employee_id.name
                )

        _logger.info("=" * 80)
        _logger.info("ICICI OTP VERIFIED")
        _logger.info("Payment Date : %s", self.payment_date)
        _logger.info("Payslips : %s", self.payslip_ids.ids)
        _logger.info("=" * 80)

        try:

            self.payslip_ids.process_bulk_payment(
                otp,
                self.payment_date,
            )

            _logger.info(
                "ICICI Bulk Payment submitted successfully."
            )

            return {
                "type": "ir.actions.client",
                "tag": "reload",
            }

        except ValidationError:
            raise

        except Exception as exc:

            _logger.exception(
                "Unexpected ICICI Bulk Payment Error."
            )

            raise ValidationError(
                _(
                    "An unexpected error occurred while processing the salary payment."
                )
            ) from exc


class IciciReverseWizard(models.TransientModel):
    _name = "icici.reverse.wizard"
    _description = "ICICI Reverse Payment Wizard"

    payslip_id = fields.Many2one(
        "hr.payslip",
        string="Payslip",
        required=True,
        readonly=True,
    )

    file_seq_num = fields.Char(
        string="File Sequence Number",
        required=True,
        readonly=True,
    )

    def action_reverse(self):
        """Reverse ICICI Salary Payment."""

        self.ensure_one()

        if not self.payslip_id:
            raise ValidationError(
                _("Payslip not found.")
            )

        if not self.file_seq_num:
            raise ValidationError(
                _("File Sequence Number is required.")
            )

        if self.payslip_id.icici_payment_status != "processing":
            raise ValidationError(
                _(
                    "Only payments in Processing state can be reversed."
                )
            )

        _logger.info("=" * 80)
        _logger.info(
            "ICICI Reverse Started : %s",
            self.payslip_id,
        )
        _logger.info("=" * 80)

        try:

            self.payslip_id.action_reverse_payment(
                self.file_seq_num
            )

            _logger.info(
                "ICICI payment reversed successfully."
            )

            return {
                "type": "ir.actions.client",
                "tag": "reload",
            }

        except ValidationError:
            raise

        except Exception as exc:

            _logger.exception(
                "Unexpected ICICI Reverse Payment Error."
            )

            raise ValidationError(
                _(
                    "An unexpected error occurred while reversing the payment."
                )
            ) from exc