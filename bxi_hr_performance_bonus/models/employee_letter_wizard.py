from odoo import models, fields, _
# pyrefly: ignore [missing-import]
from odoo.exceptions import UserError
import base64


class EmployeeLetterWizard(models.TransientModel):
    _name = 'employee.letter.wizard'
    _description = 'Employee Letter Wizard'

    appraisal_id = fields.Many2one(
        'hr.employee.appraisal'
    )

    def action_send(self):
        self.ensure_one()
        appraisal = self.appraisal_id.sudo()
        employee = appraisal.employee_id.sudo()
        if not employee.work_email:
            raise UserError(_("The selected employee does not have a work email address."))

        if not appraisal.template_company_id:
            raise UserError(_("Please Selected The Template Company"))

        letter_type = appraisal.letter_type
        report_xmlid = False
        letter_name = ""

        if letter_type == 'bonus_letter':
            report_xmlid = 'bxi_hr_performance_bonus.action_report_employee_bonus_letter'
            letter_name = "Bonus_Letter"
        elif letter_type == 'appraisal_promotion_letter':
            report_xmlid = 'bxi_hr_performance_bonus.action_report_appraisal_letter'
            letter_name = "Appraisal_and_Promotion_Letter"
        elif letter_type == 'appraisal_letter':
            report_xmlid = 'bxi_hr_performance_bonus.action_report_appraisal_letter'
            letter_name = "Appraisal_Letter"
        elif letter_type == 'promotion_letter':
            report_xmlid = 'bxi_hr_performance_bonus.action_report_promotion_letter'
            letter_name = "Promotion_Letter"

        if not report_xmlid:
            raise UserError(_("No report configured for this letter type."))

        try:
            report = self.env.ref(report_xmlid)
        except ValueError:
            raise UserError(_("Report Not Found."))

        pdf_content, dummy = report.sudo()._render_qweb_pdf(report_xmlid, res_ids=[appraisal.id])

        attachment = self.env['ir.attachment'].sudo().create({
            'name': f"{letter_name}_{employee.name}.pdf",
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': 'hr.employee.appraisal',
            'res_id': appraisal.id,
            'mimetype': 'application/pdf'
        })

        subject = ""
        body_html = ""

        if letter_type == 'bonus_letter':
            subject = f"Congratulations on your Performance Bonus, {employee.name}!"
            body_html = f"""
            <div style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.6; color: #333333;">
                <p>Dear <strong>{employee.name}</strong>,</p>
                <p>We are delighted to congratulate you on your outstanding performance and contribution to our organization!</p>
                <p>As a token of our appreciation, we are pleased to award you a performance bonus. Please find your official <strong>Bonus Letter</strong> attached to this email.</p>
                <p>Thank you for your hard work, dedication, and continued commitment. We look forward to achieving many more milestones together!</p>
                <br/>
                <p>Sincerely,</p>
                <p><strong>HR Department</strong><br/>{appraisal.template_company_id.name}</p>
            </div>
            """
        elif letter_type == 'appraisal_promotion_letter':
            subject = f"Congratulations on your Appraisal & Promotion, {employee.name}!"
            body_html = f"""
            <div style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.6; color: #333333;">
                <p>Dear <strong>{employee.name}</strong>,</p>
                <p>We are absolutely thrilled to congratulate you on your well-deserved appraisal and promotion!</p>
                <p>This milestone is a direct reflection of your dedication, passion, and valuable contributions to the company's growth. Please find your official <strong>Appraisal and Promotion Letter</strong> attached to this email.</p>
                <p>Thank you for your exceptional commitment to excellence. We are excited about your future and look forward to your continued success in your new role!</p>
                <br/>
                <p>Sincerely,</p>
                <p><strong>HR Department</strong><br/>{appraisal.template_company_id.name}</p>
            </div>
            """
        elif letter_type == 'appraisal_letter':
            subject = f"Congratulations on your Appraisal, {employee.name}!"
            body_html = f"""
            <div style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.6; color: #333333;">
                <p>Dear <strong>{employee.name}</strong>,</p>
                <p>We are pleased to congratulate you on your performance review and appraisal!</p>
                <p>Your hard work and dedication have played a key role in our collective success. Please find your official <strong>Appraisal Letter</strong> attached to this email.</p>
                <p>Thank you for your continued commitment. We look forward to supporting you in your ongoing career growth with us!</p>
                <br/>
                <p>Sincerely,</p>
                <p><strong>HR Department</strong><br/>{appraisal.template_company_id.name}</p>
            </div>
            """
        else:
            subject = f"Congratulations on your Promotion, {employee.name}!"
            body_html = f"""
            <div style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.6; color: #333333;">
                <p>Dear <strong>{employee.name}</strong>,</p>
                <p>We are extremely delighted to congratulate you on your promotion!</p>
                <p>This promotion is a testament to your hard work, dedication, and leadership. Please find your official <strong>Promotion Letter</strong> attached to this email.</p>
                <p>Thank you for your continuous efforts and passion. We wish you the absolute best of luck and success in your new responsibilities!</p>
                <br/>
                <p>Sincerely,</p>
                <p><strong>HR Department</strong><br/>{appraisal.template_company_id.name}</p>
            </div>
            """

        mail_values = {
            'subject': subject,
            'body_html': body_html,
            'email_to': employee.work_email,
            'email_from': 'hrsupport@bxitech.com',
            'attachment_ids': [(6, 0, [attachment.id])],
            'model': 'hr.employee.appraisal',
            'res_id': appraisal.id,
        }
        mail = self.env['mail.mail'].sudo().create(mail_values)
        mail.send()

        appraisal.message_post(
            body=_("Letter sent to %s via email.") % employee.name,
            subject=subject,
            attachment_ids=[attachment.id]
        )

        appraisal.state = 'released'

    def action_download(self):
        self.ensure_one()
        report_xmlid = False
        letter_type = self.appraisal_id.letter_type

        if not self.appraisal_id.template_company_id:
            raise UserError(_("Please Selected The Template Company"))

        if letter_type == 'bonus_letter':
            report_xmlid = (
                'bxi_hr_performance_bonus.action_report_employee_bonus_letter'
            )
        elif letter_type == 'appraisal_promotion_letter':
            report_xmlid = (
                'bxi_hr_performance_bonus.action_report_appraisal_letter'
            )
        elif letter_type == 'appraisal_letter':
            report_xmlid = (
                'bxi_hr_performance_bonus.action_report_appraisal_letter'
            )
        elif letter_type == 'promotion_letter':
            report_xmlid = (
                'bxi_hr_performance_bonus.action_report_promotion_letter'
            )

        if not report_xmlid:
            raise UserError(_("No report configured for this letter type."))

        try:
            report = self.env.ref(report_xmlid)
        except ValueError:
            raise UserError(_("Report Not Found."))

        return report.report_action(self.appraisal_id)