from odoo import models, fields, api, _

class HrPayslip(models.Model):
    _inherit = 'hr.payslip'


    def action_print_custom_payslip(self):
        self.ensure_one()
        xmlid = "custom_payslip_report.action_custom_payslip_pdf"
        try:
            report = self.env.ref(xmlid)
        except ValueError:
            raise UserError(_(
                "Report Not Fount"))
        return report.report_action(self)

