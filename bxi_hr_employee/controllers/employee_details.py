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
                "job_title": employee.job_id.name,
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
                "date_from": slip.date_from,
                "date_to": slip.date_to,
                "state": slip.state,
            })
        return {
            "status": True,
            "payslips": data,
        }

    @http.route(
        "/api/employee/payslip/download/<int:payslip_id>",
        type="http",
        auth="public",
    )
    def download_payslip(self, payslip_id, **kw):
        payslip = request.env["hr.payslip"].sudo().browse(payslip_id)
        if not payslip.exists():
            return request.not_found()

        pdf, _ = request.env["ir.actions.report"].sudo()._render_qweb_pdf(
            "hr_payroll.action_report_payslip",
            [payslip.id]
        )
        headers = [
            ("Content-Type", "application/pdf"),
            (
                "Content-Disposition",
                f'attachment; filename="{payslip.name}.pdf"',
            ),
        ]
        return request.make_response(pdf, headers=headers)