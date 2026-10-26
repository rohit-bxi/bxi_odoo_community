import base64
from datetime import timedelta
import email
import secrets
import random
from venv import logger
from urllib.parse import quote
import logging
_logger = logging.getLogger(__name__)

from odoo import http, fields
from odoo.http import request


class EmployeeAPIController(http.Controller):

    @http.route('/api/employee/details',type='jsonrpc',auth='public',methods=['POST'],csrf=False)
    def get_employee_details(self, **kwargs):
        try:
            employee_email = kwargs.get('employee_email')
            if not employee_email:
                return {
                    'status': False,
                    'message': 'employee_email is required'
                }
            employee = request.env['hr.employee'].sudo().search([
                ('work_email', '=', employee_email)
            ], limit=1)
            if not employee:
                return {
                    'status': False,
                    'message': 'Employee not found'
                }
            return {
                'status': True,
                'message': 'Employee details fetched successfully',
                'data': {
                    'employee_name': employee.name or '',
                    'employee_email': employee.work_email or '',
                    'employee_number': employee.private_phone or '',
                    'employee_code': employee.employee_code or '',
                    'job_title': employee.job_id.name or '',
                    'company_name': employee.company_id.name or '',
                    'manager_name': employee.parent_id.name or '',
                    'date_of_joining': str(employee.emp_date_of_joining or ''),
                }
            }
        except Exception as e:
            return {
                'status': False,
                'message': str(e)
            }
    @http.route(
        "/api/employee/check_registration_token",type="jsonrpc",auth="public",methods=["POST"],csrf=False,)
    def check_registration_token(self, **kwargs):
        token = kwargs.get("token")
        if not token:
            return {
                "status": False,
                "message": "Token is required."
            }
        employee = request.env["hr.employee"].sudo().search([
            ("portal_token", "=", token),("active", "=", False)
        ], limit=1)
        if not employee:
            return {
                "status": False,
                "message": "Invalid registration link."
            }
        if (
            not employee.portal_token_expiry
            or employee.portal_token_expiry < fields.Datetime.now()
        ):
            return {
                "status": False,
                "message": "Registration link has expired."
            }
        return {
            "status": True,
            "message": "Registration link is valid.",
            "employee_id": employee.id,
            "employee_name": employee.name,
            "email": employee.private_email,
        }

    @http.route('/api/employee/send_otp',type='jsonrpc',auth='public',methods=['POST'],csrf=False)
    def send_otp(self, **post):
        token = post.get("token")
        email = post.get("email")
        if not token:
            return {    
                "status": False,
                "message": "Token is required."
            }
        if not email:
            return {
                "status": False,
                "message": "Email is required."
            }

        employee = request.env["hr.employee"].sudo().search([
            ("portal_token", "=", token),
            ("active", "=", False)
        ], limit=1)
        if not employee:
            return {
                "status": False,
                "message": "Invalid registration link."
            }
        if (
            not employee.portal_token_expiry
            or employee.portal_token_expiry < fields.Datetime.now()
        ):
            return {
                "status": False,
                "message": "Registration link expired."
            }
        if (
            not employee.private_email
            or employee.private_email.lower() != email.lower()
        ):
            return {
                "status": False,
                "message": "Email doesn't match."
            }
        otp = str(random.randint(100000, 999999))
        employee.write({
            "portal_otp": otp,
            "portal_otp_expiry": fields.Datetime.now() + timedelta(minutes=10),
            "portal_otp_verified": False,
        })
        request.env["mail.mail"].sudo().create({
            "subject": "OTP Verification",
            "email_to": employee.private_email,
            "email_from": "hrsupport@bxitech.com",
            "body_html": f"""
                <p>Hello {employee.name},</p>
                <p>Your OTP for BXI Employee Alumni Portal:</p>
                <h2>{otp}</h2>
                <p>Please use this OTP to complete your registration.</p>
                <p>This OTP is valid for 10 minutes.</p>
            """
        }).send()
        return {
            "status": True,
            "message": "OTP sent successfully."
        }
    
    @http.route('/api/employee/verify_otp',type='jsonrpc', auth='public',methods=['POST'],csrf=False)
    def verify_otp(self, **post):
        token = post.get("token")
        otp = post.get("otp")
        employee = request.env["hr.employee"].sudo().search([
            ("portal_token","=",token),
            ("active","=",False)
        ], limit=1)
        if not employee:
            return {
                "status":False,
                "message":"Invalid token."
            }
        if employee.portal_otp != otp:
            return {
                "status":False,
                "message":"Invalid OTP."
            }
        if employee.portal_otp_expiry < fields.Datetime.now():
            return {
                "status":False,
                "message":"OTP expired."
            }
        employee.write({
            "portal_otp_verified":True
        })
        return {
            "status":True,
            "message":"OTP verified successfully."
        }

    @http.route('/api/employee/create_password',type='jsonrpc',auth='public', methods=['POST'],csrf=False)
    def create_password(self, **post):
        token = post.get("token")
        password = post.get("password")
        employee = request.env["hr.employee"].sudo().search([
            ("portal_token","=",token),("active","=",False)
        ], limit=1)
        if not employee:
            return {
                "status":False,
                "message":"Invalid token."
            }
        if not employee.portal_otp_verified:
            return {
                "status":False,
                "message":"OTP verification required."
            }
        employee.write({
            "portal_password": password
        })
        return {
            "status":True,
            "message":"Password created successfully."
        }

    @http.route("/api/employee/login",type="jsonrpc",auth="public",methods=["POST"],csrf=False)
    def employee_login(self, **post):
        email = post.get("email")
        password = post.get("password")
        if not email:
            return {
                "status": False,
                "message": "Email is required."
            }
        if not password:
            return {
                "status": False,
                "message": "Password is required."
            }
        employee = request.env["hr.employee"].sudo().search([
            ("private_email", "=", email),
            ("active", "=", False),
        ], limit=1)
        if not employee:
            return {
                "status": False,
                "message": "Employee not found."
            }
        if not employee.portal_password:
            return {
                "status": False,
                "message": "Please complete registration first."
            }
        if employee.portal_password != password:
            return {
                "status": False,
                "message": "Invalid password."
            }
        return {
            "status": True,
            "message": "Login successful.",
            "employee": {
                "employee_id": employee.id,
                "employee_code": employee.employee_code,
                "name": employee.name,
                "email": employee.private_email,
                "job_title": employee.job_title,
                "private_street": employee.private_street or False,
                "emergency_contact": employee.emergency_contact or False,
                "emergency_phone": employee.emergency_phone or False,
                "hr_responsible": (
                    employee.hr_responsible_id.name
                    if employee.hr_responsible_id
                    else False
                ),
                "department": (
                    employee.department_id.name
                    if employee.department_id
                    else False
                ),
                "date_of_joining": (
                    str(employee.emp_date_of_joining)
                    if employee.emp_date_of_joining
                    else False
                ),
                "date_of_leaving": (
                    str(employee.date_of_leaving)
                    if employee.date_of_leaving
                    else False
                ),
            }
        }

    @http.route("/api/employee/payslips",type="jsonrpc",auth="public",methods=["POST"],csrf=False)
    def employee_payslips(self, **post):
        email = post.get("email")
        employee = request.env["hr.employee"].sudo().search([
            ("private_email", "=", email),
            ("active", "=", False),
        ], limit=1)
        if not employee:
            return {
                "status": False,
                "message": "Employee not found."
            }
        payslips = request.env["hr.payslip"].sudo().search(
            [("employee_id", "=", employee.id)],
            order="date_to desc",
        )
        data = []
        for slip in payslips:
            data.append({
                "id": slip.id,
                "name": slip.name,
                "month": slip.date_to.strftime("%B %Y") if slip.date_to else False,
                "state": slip.state,
            })
        return {
            "status": True,
            "employee_id": employee.id,
            "payslips": data,
        }
    
    @http.route("/api/employee/payslip/<int:payslip_id>/view",type="http",auth="public",methods=["GET"],csrf=False,)
    def view_payslip(self, payslip_id, **kw):
        email = kw.get("email")
        if not email:
            return request.make_response(
                "Email is required.",
                headers=[("Content-Type", "text/plain")],
                status=400,
            )
        employee = request.env["hr.employee"].sudo().search([
            ("private_email", "=", email),
            ("active", "=", False),
        ], limit=1)
        if not employee:
            return request.not_found()
        payslip = request.env["hr.payslip"].sudo().search([
            ("id", "=", payslip_id),
            ("employee_id", "=", employee.id),
        ], limit=1)
        if not payslip:
            return request.not_found()
        pdf, _ = request.env["ir.actions.report"].sudo()._render_qweb_pdf(
            "custom_payslip_report.action_custom_payslip_pdf",
            [payslip.id],
        )
        headers = [
            ("Content-Type", "application/pdf"),
            (
                "Content-Disposition",
                f'inline; filename="{payslip.name}.pdf"',
            ),
        ]
        return request.make_response(pdf, headers=headers)

    @http.route("/api/employee/payslip/<int:payslip_id>/download",type="http",auth="public",methods=["GET"],csrf=False,)
    def download_payslip(self, payslip_id, **kw):
        email = kw.get("email")
        if not email:
            return request.make_response(
                "Email is required.",
                headers=[("Content-Type", "text/plain")],
                status=400,
            )
        employee = request.env["hr.employee"].sudo().search([
            ("private_email", "=", email),
            ("active", "=", False),
        ], limit=1)
        if not employee:
            return request.not_found()
        payslip = request.env["hr.payslip"].sudo().search([
            ("id", "=", payslip_id),
            ("employee_id", "=", employee.id),
        ], limit=1)
        if not payslip:
            return request.not_found()
        pdf, _ = request.env["ir.actions.report"].sudo()._render_qweb_pdf(
            "custom_payslip_report.action_custom_payslip_pdf",
            [payslip.id],
        )
        filename = f"{payslip.name}.pdf"
        headers = [
            ("Content-Type", "application/pdf"),
            (
                "Content-Disposition",
                f'attachment; filename="{filename}"',
            ),
        ]
        return request.make_response(pdf, headers=headers)

    @http.route("/api/employee/signed_experience_letter_view",type="http",auth="public",methods=["GET"],csrf=False,)
    def signed_experience_letter_view(self, **kw):
        employee_id = kw.get("employee_id")
        if not employee_id:
            return request.make_response(
                "employee_id is required",
                headers=[("Content-Type", "text/plain")],
                status=400,
            )
        try:
            employee_id = int(employee_id)
        except (TypeError, ValueError):
            return request.make_response(
                "Invalid employee_id",
                headers=[("Content-Type", "text/plain")],
                status=400,
            )

        employee = request.env["hr.employee"].sudo().browse(employee_id)

        if not employee.exists():
            return request.make_response(
                "Employee not found",
                headers=[("Content-Type", "text/plain")],
                status=404,
            )

        signed_document = employee.signed_experience_letter
        if not signed_document:
            return request.make_response(
                "Signed Experience Letter is not uploaded.",
                headers=[("Content-Type", "text/plain")],
                status=404,
            )
        try:
            pdf_content = base64.b64decode(signed_document)
        except Exception:
            return request.make_response(
                "Unable to read the signed Experience Letter.",
                headers=[("Content-Type", "text/plain")],
                status=500,
            )

        filename = (
            employee.signed_experience_letter_filename
            or "Signed_Experience_Letter.pdf"
        )

        return request.make_response(
            pdf_content,
            headers=[
                ("Content-Type", "application/pdf"),
                (
                    "Content-Disposition",
                    f'inline; filename="{filename}"',
                ),
            ],
        )
    
    @http.route("/api/employee/signed_experience_letter_download",type="http",auth="public",methods=["GET"],csrf=False,)
    def signed_experience_letter_download(self, **kw):
        employee_id = kw.get("employee_id")
        if not employee_id:
            return request.make_response(
                "employee_id is required",
                headers=[("Content-Type", "text/plain")],
                status=400,
            )
        try:
            employee_id = int(employee_id)
        except (TypeError, ValueError):
            return request.make_response(
                "Invalid employee_id",
                headers=[("Content-Type", "text/plain")],
                status=400,
            )
        employee = request.env["hr.employee"].sudo().browse(employee_id)
        if not employee.exists():
            return request.make_response(
                "Employee not found.",
                headers=[("Content-Type", "text/plain")],
                status=404,
            )
        if not employee.signed_experience_letter:
            return request.make_response(
                "Signed Experience Letter is not available.",
                headers=[("Content-Type", "text/plain")],
                status=404,
            )
        try:
            pdf_content = base64.b64decode(
                employee.signed_experience_letter
            )
        except Exception:
            return request.make_response(
                "Invalid signed Experience Letter file.",
                headers=[("Content-Type", "text/plain")],
                status=500,
            )

        filename = (
            employee.signed_experience_letter_filename
            or "Signed_Experience_Letter.pdf"
        )
        return request.make_response(
            pdf_content,
            headers=[
                ("Content-Type", "application/pdf"),
                (
                    "Content-Disposition",
                    f'attachment; filename="{filename}"',
                ),
            ],
        )
 
    @http.route("/api/employee/forgot_password",type="jsonrpc",auth="public",methods=["POST"],csrf=False,)
    def forgot_password(self, **post):
        email = (post.get("email") or "").strip().lower()
        if not email:
            return {
                "status": False,
                "message": "Personal email is required.",
            }
        employee = request.env["hr.employee"].sudo().search([
            ("private_email", "=ilike", email),
            ("active", "=", False),
        ], limit=1)
        if not employee:
            return {
                "status": False,
                "message": "Please enter your registered personal email.",
            }
        reset_token = secrets.token_urlsafe(32)
        expiry = fields.Datetime.now() + timedelta(hours=24)
        employee.sudo().write({
            "portal_reset_token": reset_token,
            "portal_reset_token_expiry": expiry,
        })
        reset_link = (
            f"https://alumni.bxiventures.com/reset-password"
            f"?token={reset_token}"
        )
        mail = request.env["mail.mail"].sudo().create({
            "subject": "Reset Your Employee Alumni Portal Password",
            "email_to": employee.private_email,
            "email_from":"hrsupport@bxitech.com",
            "body_html": f"""
                <p>Dear {employee.name},</p>
                <p>
                    We received a request to reset your Employee Alumni Portal
                    password.
                </p>
                <p>
                    Please click the button below to reset your password:
                </p>
                <p>
                    <a href="{reset_link}"
                    style="
                        background:#875A7B;
                        color:white;
                        padding:10px 20px;
                        text-decoration:none;
                        border-radius:5px;
                        display:inline-block;
                    ">
                        Reset Password
                    </a>
                </p>
                <p>
                    This password reset link is valid for
                    <strong>24 hours</strong>.
                </p>
                <p>
                    If you did not request a password reset,
                    please ignore this email.
                </p>
                <p>
                    Best regards,<br/>
                    HR Team
                </p>
            """,
        })
        mail.send()
        return {
            "status": True,
            "message": "Password reset link has been sent to your personal email.",
        }

    @http.route("/api/employee/reset_password",type="jsonrpc",auth="public",methods=["POST"],csrf=False,)
    def reset_password(self, **post):
        token = (post.get("token") or "").strip()
        password = post.get("password")
        if not token:
            return {
                "status": False,
                "message": "Reset token is required.",
            }
        if not password:
            return {
                "status": False,
                "message": "New password is required.",
            }
        if len(password) < 8:
            return {
                "status": False,
                "message": "Password must contain at least 8 characters.",
            }
        employee = request.env["hr.employee"].sudo().search([
            ("portal_reset_token", "=", token),
            ("active", "=", False),
        ], limit=1)
        if not employee:
            return {
                "status": False,
                "message": "Invalid or expired reset link.",
            }
        if (
            not employee.portal_reset_token_expiry
            or employee.portal_reset_token_expiry < fields.Datetime.now()
        ):
            return {
                "status": False,
                "message": "Reset link has expired. Please request a new link.",
            }
        employee.sudo().write({
            "portal_password": password,
            "portal_reset_token": False,
            "portal_reset_token_expiry": False,
        })
        return {
            "status": True,
            "message": "Password reset successfully.",
        }

    @http.route("/api/employee/form16/view",type="http",auth="public",methods=["GET"],csrf=False,)
    def view_form16(self, **kw):
        email = (kw.get("email") or "").strip()
        if not email:
            return request.make_response(
                "Email is required.",
                headers=[("Content-Type", "text/plain")],
                status=400,
            )
        employee = request.env["hr.employee"].sudo().search([
            ("private_email", "=ilike", email),
            ("active", "=", False),
        ], limit=1)
        if not employee:
            return request.make_response(
                "Employee not found.",
                headers=[("Content-Type", "text/plain")],
                status=404,
            )
        if not employee.form_16:
            return request.make_response(
                "Form 16 is not available.",
                headers=[("Content-Type", "text/plain")],
                status=404,
            )
        try:
            pdf_content = base64.b64decode(employee.form_16)
        except Exception:
            return request.make_response(
                "Invalid Form 16 file.",
                headers=[("Content-Type", "text/plain")],
                status=500,
            )
        filename = employee.form_16_filename or "Form_16.pdf"
        return request.make_response(
            pdf_content,
            headers=[
                ("Content-Type", "application/pdf"),
                (
                    "Content-Disposition",
                    f'inline; filename="{filename}"',
                ),
            ],
        )

    @http.route("/api/employee/form16/download",type="http",auth="public",methods=["GET"],csrf=False,)
    def download_form16(self, **kw):
        email = (kw.get("email") or "").strip()
        if not email:
            return request.make_response(
                "Email is required.",
                headers=[("Content-Type", "text/plain")],
                status=400,
            )
        employee = request.env["hr.employee"].sudo().search([
            ("private_email", "=ilike", email),
            ("active", "=", False),
        ], limit=1)
        if not employee:
            return request.make_response(
                "Employee not found.",
                headers=[("Content-Type", "text/plain")],
                status=404,
            )
        if not employee.form_16:
            return request.make_response(
                "Form 16 is not available.",
                headers=[("Content-Type", "text/plain")],
                status=404,
            )
        try:
            pdf_content = base64.b64decode(employee.form_16)
        except Exception:
            return request.make_response(
                "Invalid Form 16 file.",
                headers=[("Content-Type", "text/plain")],
                status=500,
            )
        filename = (
            employee.form_16_filename
            or "Form_16.pdf"
        )
        return request.make_response(
            pdf_content,
            headers=[
                ("Content-Type", "application/pdf"),
                (
                    "Content-Disposition",
                    f'attachment; filename="{filename}"',
                ),
            ],
        )

    @http.route(
        "/api/employee/archived",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def archived_employee_list(self, **post):
        employees = request.env["hr.employee"].sudo().search([
            ("active", "=", False),
        ])
        employee_data = []
        for employee in employees:
            employee_data.append({
                "id": employee.id,
                "name": employee.name or False,
                "email": employee.private_email or False,
                "phone": employee.private_phone or False,
                "employee_code": employee.employee_code or False,
                "job_title": employee.job_title or False,
                "company": employee.company_id.name or False,
                "manager": employee.parent_id.name or False,
                "is_fnf_done" : employee.is_fnf_done or False,
                "is_pf_done":employee.is_pf_done or False,
                "re_hire" : employee.re_hire or False,
                "rehire_not_description": (
                    employee.rehire_not_description
                    if employee.rehire_not_description
                    else False
                ),
                "date_of_joining": (
                    str(employee.emp_date_of_joining)
                    if employee.emp_date_of_joining
                    else False
                ),
                "date_of_leaving": (
                    str(employee.date_of_leaving)
                    if employee.date_of_leaving
                    else False
                ),
                "departure_reason": (
                    employee.departure_reason_id.name
                    if employee.departure_reason_id
                    else False
                ),
                "departure_description": (
                    employee.departure_description
                    if employee.departure_description
                    else False
                ),
                "hr_responsible": (
                    employee.hr_responsible_id.name
                    if employee.hr_responsible_id
                    else False
                ),

                "department": (
                    employee.department_id.name
                    if employee.department_id
                    else False
                ),
                "fnf_status": employee.fnf_status or False,
                "expected_clearance":employee.expected_clearance or False,
                "hr_clearance": employee.hr_clearance or False,
                "hr_clearance_reason": (
                    employee.hr_clearance_reason or False
                ),
                "hr_clearance_status": (
                    employee.hr_clearance_status or False
                ),
                "rm_clearance": employee.rm_clearance or False,
                "rm_clearance_reason": (
                    employee.rm_clearance_reason or False
                ),
                "rm_clearance_status": (
                    employee.rm_clearance_status or False
                ),
                "it_clearance": employee.it_clearance or False,
                "it_clearance_reason": (
                    employee.it_clearance_reason or False
                ),
                "it_clearance_status": (
                    employee.it_clearance_status or False
                ),
                "finance_clearance": employee.finance_clearance or False,
                "finance_clearance_reason": (
                    employee.finance_clearance_reason or False
                ),
                "finance_clearance_status": (
                    employee.finance_clearance_status or False
                ),
            })
        return {
            "status": True,
            "count": len(employee_data),
            "employees": employee_data,
        }

    @http.route(
        "/api/employee/verify_aadhar",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def verify_aadhar(self, **post):
        aadhar_card = (post.get("aadhar_card") or "").strip()
        if not aadhar_card:
            return {
                "status": False,
                "message": "Aadhar card number is required.",
            }
        employee = request.env["hr.employee"].sudo().search([
            ("aadhar_card", "=", aadhar_card),
            ("active", "=", False),
        ], limit=1)
        if not employee:
            return {
                "status": False,
                "message": "Aadhar card number does not match our records.",
            }
        return {
            "status": True,
            "message": "Aadhar card verified successfully.",
            "employee_id": employee.id,
            "aadhar_card": employee.aadhar_card,
            "redirect_url": (
                "https://alumni.bxiventures.com/create-credentials"
                f"?aadhar_card={employee.aadhar_card}"
                f"&employee_id={employee.employee_id.id}"
            ),
        }
    
    @http.route(
        "/api/employee/create_new_credentials",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def create_new_credentials(self, **post):
        employee_id = post.get("employee_id")
        new_email = (post.get("new_email") or "").strip()
        if not employee_id:
            return {
                "status": False,
                "message": "Employee ID is required.",
            }
        if not new_email:
            return {
                "status": False,
                "message": "New email is required.",
            }
    
        employee = request.env["hr.employee"].sudo().search([
            ("id", "=", int(employee_id)),
            ("active", "=", False),
        ], limit=1)

        if not employee:
            return {
                "status": False,
                "message": "Employee not found.",
            }
        existing_employee = request.env["hr.employee"].sudo().search([
            ("private_email", "=ilike", new_email),
            ("id", "!=", employee.id),
        ], limit=1)

        if existing_employee:
            return {
                "status": False,
                "message": "This email address is already registered.",
            }
        employee.sudo().write({
            "private_email": new_email,
        })
        try:
            employee.sudo().action_send_registration_link()

        except Exception:
            logger.exception(
                "Failed to send registration link to %s",
                new_email,
            )
            return {
                "status": False,
                "message": (
                    "Email and password were updated, "
                    "but the registration link could not be sent."
                ),
            }
        return {
            "status": True,
            "message": (
                "Your email have been updated successfully. "
                "A registration link has been sent to your new email address."
            ),
            "email": new_email,
            "employee_id": employee.id,
        }

    @http.route(
        "/api/employee/edit_profile",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def edit_employee_profile(self, **post):
        email = (post.get("email") or "").strip()
        if not email:
            return {
                "status": False,
                "message": "Email is required.",
            }
        employee = request.env["hr.employee"].sudo().search([
            ("private_email", "=ilike", email),
            ("active", "=", False),
        ], limit=1)
        if not employee:
            return {
                "status": False,
                "message": "Employee not found.",
            }

        vals = {}
        if "private_street" in post:
            vals["private_street"] = (post.get("private_street") or "").strip()
        if "emergency_contact" in post:
            vals["emergency_contact"] = (
                post.get("emergency_contact") or ""
            ).strip()
        if "emergency_phone" in post:
            vals["emergency_phone"] = (
                post.get("emergency_phone") or ""
            ).strip()
        if not vals:
            return {
                "status": False,
                "message": "No profile information provided to update.",
            }
        employee.write(vals)
        return {
            "status": True,
            "message": "Profile updated successfully.",
            "employee": {
                "id": employee.id,
                "name": employee.name,
                "email": employee.private_email,
                "private_street": employee.private_street or False,
                "emergency_contact": employee.emergency_contact or False,
                "emergency_phone": employee.emergency_phone or False,
            },
        }

    @http.route(
        '/api/employee/offboarding/tasks/<int:employee_id>',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
    )
    def get_offboarding_tasks(self, employee_id, **kwargs):

        employee = request.env['hr.employee'].sudo().browse(employee_id)

        if not employee.exists():
            return request.make_json_response(
                {
                    'success': False,
                    'message': 'Employee not found.',
                },
                status=404,
            )

        # Find OFFBOARDING records using offboarding_employee_id
        onboarding_records = request.env[
            'employee.onboarding.offboarding'
        ].sudo().search([
            ('offboarding_employee_id', '=', employee_id),
        ])

        if not onboarding_records:
            return request.make_json_response(
                {
                    'success': True,
                    'employee_id': employee.id,
                    'employee_name': employee.name,
                    'total_tasks': 0,
                    'completed_tasks': 0,
                    'incomplete_tasks': 0,
                    'review_pending': 0,
                    'review_done': 0,
                    'data': [],
                    'message': 'No offboarding records found for this employee.',
                },
                status=200,
            )

        # Find tasks linked with the offboarding records
        tasks = request.env[
            'employee.onboarding.task'
        ].sudo().search(
            [
                ('onboarding_id', 'in', onboarding_records.ids),
            ],
            order='sequence asc, id asc',
        )

        status_selection = dict(
            request.env[
                'employee.onboarding.task'
            ]._fields['status'].selection
        )

        review_selection = dict(
            request.env[
                'employee.onboarding.task'
            ]._fields['review'].selection
        )

        task_data = []

        for task in tasks:

            task_data.append({
                'task_id': task.id,

                'offboarding_id': (
                    task.onboarding_id.id
                    if task.onboarding_id
                    else False
                ),

                'offboarding_name': (
                    task.onboarding_id.name
                    if task.onboarding_id
                    else False
                ),

                'task': task.task,

                'sequence': task.sequence,

                'performed_by': (
                    task.performed_by.name
                    if task.performed_by
                    else False
                ),

                'status': task.status,

                'status_label': status_selection.get(
                    task.status
                ),

                'review': task.review,

                'review_label': review_selection.get(
                    task.review
                ),
            })

        completed_tasks = tasks.filtered(
            lambda t: t.status == 'completed'
        )

        incomplete_tasks = tasks.filtered(
            lambda t: t.status == 'incomplete'
        )

        review_pending = tasks.filtered(
            lambda t: t.review == 'pending'
        )

        review_done = tasks.filtered(
            lambda t: t.review == 'done'
        )

        total_tasks = len(tasks)

        completion_percentage = (
            len(completed_tasks) * 100 / total_tasks
            if total_tasks
            else 0
        )

        review_percentage = (
            len(review_done) * 100 / total_tasks
            if total_tasks
            else 0
        )

        return request.make_json_response(
            {
                'success': True,

                'employee_id': employee.id,

                'employee_name': employee.name,

                'total_offboarding_records': len(
                    onboarding_records
                ),

                'total_tasks': total_tasks,

                'completed_tasks': len(
                    completed_tasks
                ),

                'incomplete_tasks': len(
                    incomplete_tasks
                ),

                'review_pending': len(
                    review_pending
                ),

                'review_done': len(
                    review_done
                ),

                'completion_percentage': round(
                    completion_percentage,
                    2,
                ),

                'review_percentage': round(
                    review_percentage,
                    2,
                ),

                'data': task_data,
            },
            status=200,
        )

LETTER_REPORT_XMLIDS = {
    "bonus_letter":"bxi_hr_performance_bonus.action_report_employee_bonus_letter",
    "appraisal_promotion_letter":"bxi_hr_performance_bonus.action_report_appraisal_letter",
    "appraisal_letter":"bxi_hr_performance_appraisal.action_report_appraisal_letter",
    "promotion_letter":"bxi_hr_performance_bonus.action_report_promotion_letter",
}

class EmployeeLetterAPI(http.Controller):

    def _text_response(self, message, status=400):
        response = request.make_response(
            message,
            headers=[
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Cache-Control", "no-store"),
            ],
        )
        response.status_code = status
        return response

    def _get_archived_employee(self, email):
        email = (email or "").strip()

        if not email:
            return request.env["hr.employee"]

        return request.env["hr.employee"].sudo().search(
            [
                ("private_email", "=ilike", email),
                ("active", "=", False),
            ],
            limit=1,
        )

    def _get_employee_letter(self, letter_id, email):
        employee = self._get_archived_employee(email)

        if not employee:
            return employee, request.env["hr.employee.appraisal"]

        letter = request.env["hr.employee.appraisal"].sudo().search(
            [
                ("id", "=", letter_id),
                ("employee_id", "=", employee.id),
                ("state", "=", "released"),
            ],
            limit=1,
        )

        return employee, letter

    def _get_report_action(self, report_xmlid):
        if not report_xmlid:
            return False

        try:
            module_name, record_name = report_xmlid.split(".", 1)
        except ValueError:
            _logger.error("Invalid report XML ID: %s", report_xmlid)
            return False

        xmlid_record = request.env["ir.model.data"].sudo().search(
            [
                ("module", "=", module_name),
                ("name", "=", record_name),
                ("model", "=", "ir.actions.report"),
            ],
            limit=1,
        )

        if not xmlid_record:
            _logger.error(
                "Report XML ID does not exist: %s",
                report_xmlid,
            )
            return False

        return request.env["ir.actions.report"].sudo().browse(
            xmlid_record.res_id
        ).exists()


    @http.route("/api/employee/letters",type="jsonrpc",auth="public",methods=["POST"],csrf=False)
    def employee_letters(self, **post):
        email = (post.get("email") or "").strip()

        if not email:
            return {
                "status": False,
                "message": "Email is required.",
                "letters": [],
            }

        employee = self._get_archived_employee(email)

        if not employee:
            return {
                "status": False,
                "message": "Archived employee not found.",
                "letters": [],
            }

        Appraisal = request.env["hr.employee.appraisal"].sudo()

        letters = Appraisal.search(
            [
                ("employee_id", "=", employee.id),
                ("state", "=", "released"),
            ],
            order="release_date desc, id desc",
        )

        letter_labels = dict(
            Appraisal._fields["letter_type"].selection
        )

        safe_email = quote(email, safe="")
        data = []

        for letter in letters:
            data.append({
                "id": letter.id,
                "name": letter_labels.get(
                    letter.letter_type,
                    "Employee Letter",
                ),
                "letter_type": letter.letter_type or False,
                "state": letter.state,
                "release_date": (
                    letter.release_date.strftime("%Y-%m-%d")
                    if letter.release_date
                    else False
                ),
                "effective_date": (
                    letter.effective_date.strftime("%Y-%m-%d")
                    if letter.effective_date
                    else False
                ),
                "view_url": (
                    f"/api/employee/letters/{letter.id}/view"
                    f"?email={safe_email}"
                ),
                "download_url": (
                    f"/api/employee/letters/{letter.id}/download"
                    f"?email={safe_email}"
                ),
            })

        return {
            "status": True,
            "employee_id": employee.id,
            "total_letters": len(data),
            "letters": data,
        }

    def _prepare_report_record(self, letter, report):
        """
        Return (record_id, temporary_wizard).

        If the report is defined on hr.employee.appraisal, use the
        appraisal record directly.

        If the report is defined on employee.letter.wizard, create a
        temporary wizard using the appraisal and letter type.
        """

        if report.model == "hr.employee.appraisal":
            return letter.id, False

        if report.model != "employee.letter.wizard":
            _logger.error(
                "Unsupported report model %s for report %s",
                report.model,
                report.name,
            )
            raise ValueError(
                "The report model must be hr.employee.appraisal "
                "or employee.letter.wizard."
            )

        Wizard = request.env["employee.letter.wizard"].sudo()

        wizard_values = {}

        if "appraisal_id" in Wizard._fields:
            wizard_values["appraisal_id"] = letter.id

        if "letter_type" in Wizard._fields:
            wizard_values["letter_type"] = letter.letter_type

        # Keep default_appraisal_id compatible with the context used
        # by action_open_letter_wizard() in the appraisal model.
        Wizard = Wizard.with_context(
            default_appraisal_id=letter.id,
        )

        wizard = Wizard.create(wizard_values)

        return wizard.id, wizard

    def _get_letter_pdf(self, letter, download=False):
        report_xmlid = LETTER_REPORT_XMLIDS.get(
            letter.letter_type
        )

        if not report_xmlid:
            return self._text_response(
                "No report is configured for letter type: %s"
                % (letter.letter_type or "unknown"),
                status=500,
            )

        report = self._get_report_action(report_xmlid)

        if not report:
            return self._text_response(
                "The configured PDF report was not found: %s"
                % report_xmlid,
                status=500,
            )

        temporary_wizard = False

        try:
            report_record_id, temporary_wizard = (
                self._prepare_report_record(letter, report)
            )

            pdf_content, _ = (
                request.env["ir.actions.report"].sudo()._render_qweb_pdf(
                    report_xmlid,
                    [report_record_id],
                )
            )

            if not pdf_content:
                return self._text_response(
                    "The report did not generate PDF content.",
                    status=500,
                )

        except Exception:
            _logger.exception(
                "Could not render letter %s using report %s",
                letter.id,
                report_xmlid,
            )
            return self._text_response(
                "Unable to generate the letter PDF. "
                "Check the Odoo server log for details.",
                status=500,
            )

        finally:
            # The wizard is transient and is only created to render
            # the PDF for this request.
            if temporary_wizard and temporary_wizard.exists():
                try:
                    temporary_wizard.unlink()
                except Exception:
                    _logger.exception(
                        "Could not clean up temporary letter wizard."
                    )

        Appraisal = request.env["hr.employee.appraisal"].sudo()
        letter_labels = dict(
            Appraisal._fields["letter_type"].selection
        )

        label = letter_labels.get(
            letter.letter_type,
            "Employee Letter",
        )

        safe_label = "_".join(
            "".join(
                char if char.isalnum() else "_"
                for char in label
            ).split("_")
        ).strip("_")

        filename = f"{safe_label}_{letter.id}.pdf"
        disposition = "attachment" if download else "inline"

        return request.make_response(
            pdf_content,
            headers=[
                ("Content-Type", "application/pdf"),
                (
                    "Content-Disposition",
                    f'{disposition}; filename="{filename}"',
                ),
                ("Content-Length", str(len(pdf_content))),
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
            ],
        )


    @http.route("/api/employee/letters/<int:letter_id>/view",type="http",auth="public",methods=["GET"],csrf=False)
    def view_employee_letter(self, letter_id, **kw):
        email = (kw.get("email") or "").strip()

        if not email:
            return self._text_response(
                "Email is required.",
                status=400,
            )

        employee, letter = self._get_employee_letter(
            letter_id,
            email,
        )

        if not employee or not letter:
            return request.not_found()

        return self._get_letter_pdf(
            letter,
            download=False,
        )

    @http.route("/api/employee/letters/<int:letter_id>/download",type="http",auth="public",methods=["GET"],csrf=False)
    def download_employee_letter(self, letter_id, **kw):
        email = (kw.get("email") or "").strip()

        if not email:
            return self._text_response(
                "Email is required.",
                status=400,
            )

        employee, letter = self._get_employee_letter(
            letter_id,
            email,
        )

        if not employee or not letter:
            return request.not_found()

        return self._get_letter_pdf(
            letter,
            download=True,
        )