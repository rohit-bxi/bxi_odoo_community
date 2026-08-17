import base64
from datetime import timedelta
import email
import secrets
import random

from odoo import http, fields
from odoo.http import request


class EmployeeAPIController(http.Controller):

    @http.route('/api/employee/details',type='json',auth='public',methods=['POST'],csrf=False)
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
        "/api/employee/check_registration_token",type="json",auth="public",methods=["POST"],csrf=False,)
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

    @http.route('/api/employee/send_otp',type='json',auth='public',methods=['POST'],csrf=False)
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
                <p>Your OTP is:</p>
                <h2>{otp}</h2>
                <p>This OTP is valid for 10 minutes.</p>
            """
        }).send()
        return {
            "status": True,
            "message": "OTP sent successfully."
        }
    
    @http.route('/api/employee/verify_otp',type='json', auth='public',methods=['POST'],csrf=False)
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

    @http.route('/api/employee/create_password',type='json',auth='public', methods=['POST'],csrf=False)
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

    @http.route("/api/employee/login",type="json",auth="public",methods=["POST"],csrf=False)
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
                "employee_code": employee.employee_code,
                "name": employee.name,
                "email": employee.private_email,
                "job_title": employee.job_title,
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

    @http.route("/api/employee/payslips",type="json",auth="public",methods=["POST"],csrf=False)
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
            limit=3
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
            "om_hr_payroll.action_report_payslip",
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
            "om_hr_payroll.action_report_payslip",
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

    import base64
    from odoo import http
    from odoo.http import request

    @http.route(
        "/api/employee/signed_experience_letter_view",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
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

        # Get uploaded signed document
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
    
    @http.route(
        "/api/employee/signed_experience_letter_download",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def signed_experience_letter_download(self, **kw):

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