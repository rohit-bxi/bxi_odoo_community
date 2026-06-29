import base64
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from num2words import num2words


class AccountMove(models.Model):
    _inherit = "account.move"

    amount_total_in_words = fields.Char(compute="_compute_amount_in_words", store=True)

    @api.depends("amount_total", "currency_id")
    def _compute_amount_in_words(self):
        for move in self:
            move.amount_total_in_words = num2words(move.amount_total or 0.0, lang="en_IN").title()

    def action_custom_invoice_report_pdf(self):
        self.ensure_one()
        xmlid = "custom_invoice_report.action_custom_invoice_report_pdf"
        try:
            report = self.env.ref(xmlid)
        except ValueError:
            raise UserError(_("Report Not Found"))
        return report.report_action(self)


    def _prepare_product_base_line_for_taxes_computation(self, line):
        """
        Core hook: tax and totals base quantity uses qty * months.
        """
        base_line = super()._prepare_product_base_line_for_taxes_computation(line)

        months = getattr(line, "inv_months", 1) or 1
        qty = base_line.get("quantity", line.quantity or 0.0) or 0.0
        base_line["quantity"] = qty * months

        return base_line



class AccountMoveSendWizard(models.TransientModel):
    _inherit = 'account.move.send.wizard'

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        custom_report = self.env.ref(
            'custom_invoice_report.action_custom_invoice_report_pdf',
            raise_if_not_found=False
        )

        if custom_report:
            res['pdf_report_id'] = custom_report.id

        return res

    def _get_default_pdf_report_id(self, move):
        custom_report = self.env.ref(
            'custom_invoice_report.action_custom_invoice_report_pdf',
            raise_if_not_found=False
        )