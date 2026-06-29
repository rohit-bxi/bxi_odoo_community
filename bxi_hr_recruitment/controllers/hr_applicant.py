from odoo import http
from odoo.http import request
import base64
import datetime



class ApplicantCreation(http.Controller):

    # =========================
    # RESPONSE WRAPPER
    # =========================
    def _response(self, status, message, data=None):
        return {
            "status": status,
            "message": message,
            "data": data or {}
        }

    # =========================
    # SAFE BASE64 DECODER
    # =========================
    def safe_b64decode(self, value):
        if not value:
            return None

        try:
            if "," in value:
                value = value.split(",")[1]

            missing_padding = len(value) % 4
            if missing_padding:
                value += "=" * (4 - missing_padding)

            return base64.b64decode(value)

        except Exception:
            return None

    # =========================
    # CREATE APPLICANT
    # =========================
    @http.route('/api/applicant/create', type='jsonrpc', auth='public', methods=['POST'], csrf=False)
    def create_applicant(self, **kwargs):
        try:

            partner_name = kwargs.get('partner_name')
            email = kwargs.get('email_from')
            phone = kwargs.get('partner_phone')
            job_id = kwargs.get('job_id')
            cover_letter=kwargs.get('cover_letter')

            resume_file = kwargs.get('resume_file')

            if not email:
                return self._response("error", "Email is required")

            existing_applicant = request.env['hr.applicant'].sudo().search([
                ('email_from', '=ilike', email.strip()),
                ('job_id', '=', job_id)
            ], limit=1)

            if existing_applicant:
                return self._response(
                    "error",
                    "An applicant with this email address already exists."
                )

            if not partner_name:
                return self._response("error", "Applicant name is required")

            job = request.env['hr.job'].sudo().browse(job_id)

            if not job.exists():
                return self._response("error", "Invalid Job ID")

            applicant_vals = {
                'partner_name': partner_name,
                'email_from': email,
                'partner_phone': phone,
                'job_id': job_id,
                'cover_letter': cover_letter
            }

            # -----------------------------
            #  ADD RESUME (IMPORTANT BLOCK)
            # -----------------------------
            if resume_file:
                applicant_vals.update({
                    'resume_file': resume_file,

                    'resume_filename': f"Resume_{partner_name}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
                })

            applicant = request.env['hr.applicant'].sudo().create(applicant_vals)

            template = request.env.ref(
                'bxi_hr_recruitment.email_template_applicant_submitted',
                raise_if_not_found=False
            )
            if template:
                template.sudo().send_mail(
                    applicant.id,
                    email_values={
                        'email_to': 'careers@bxitech.com',
                        'email_from': 'careers@bxitech.com',
                        'reply_to': applicant.email_from,
                    },
                    force_send=True
                )                
            return self._response(
                "success",
                "Applicant created successfully",
                {
                    "applicant_id": applicant.id,
                    "partner_name": applicant.partner_name
                }
            )

        except Exception as e:
            return self._response("error", str(e))


    ######################## SUBMIT ##############################


    @http.route('/api/application/submit', type='json', auth='public', methods=['POST'], csrf=False)
    def submit_application(self, **kwargs):
        try:
            data = kwargs
            odoo_id = data.get('odoo_id')
            if not odoo_id:
                return {
                    "status": "error",
                    "message": "Missing odoo_id"
                }
            applicant = request.env['hr.applicant'].sudo().browse(int(odoo_id))
            if not applicant.exists():
                return {
                    "status": "error",
                    "message": "Invalid applicant"
                }
            if applicant.is_application_submitted:
                return {
                    "status": "error",
                    "message": "You have already submitted your application."
                }
            applicant.write({
                'partner_name': data.get('partner_name'),
                'contact_number': data.get('contact_number'),
                'email_from': data.get('email_from'),
                'father_name': data.get('father_name'),
                'mother_name': data.get('mother_name'),
                'aadhar_number': data.get('aadhar_number'),
                'pan_number': data.get('pan_number'),
                'full_address': data.get('full_address'),
                'joining_date': data.get('joining_date'),
            })

            def create_attachment(file_obj):
                if not file_obj or not file_obj.get('data'):
                    return False

                attachment = request.env['ir.attachment'].sudo().create({
                    'name': file_obj.get('name') or 'file',
                    'type': 'binary',
                    'datas': file_obj.get('data'),
                    'res_model': 'hr.applicant',
                    'res_id': applicant.id,
                })

                return attachment.id

            def m2m(file_obj):
                attachment_id = create_attachment(file_obj)
                if attachment_id:
                    return [(4, attachment_id)]
                return []
            applicant.write({
                'doc_10th_id': m2m(data.get('doc_10th')),
                'doc_12th_id': m2m(data.get('doc_12th')),
                'doc_graduation_id': m2m(data.get('doc_graduation')),
                'doc_master_id': m2m(data.get('doc_master')),
                'any_certificate': m2m(data.get('any_certificate')),
                'photograph': m2m(data.get('photograph')),
            })
            def create_exp_attachment(file_obj, exp_record):
                if not file_obj or not file_obj.get('data'):
                    return False

                attachment = request.env['ir.attachment'].sudo().create({
                    'name': file_obj.get('name') or 'file',
                    'type': 'binary',
                    'datas': file_obj.get('data'),
                    'res_model': 'hr.applicant.experience',
                    'res_id': exp_record.id,
                })

                return attachment.id
            for exp in data.get('experience', []):
                company_name = exp.get('company_name')

                if not company_name:
                    continue

                company = request.env['hr.applicant.company'].sudo().search(
                    [('name', '=', company_name)],
                    limit=1
                )

                if not company:
                    company = request.env['hr.applicant.company'].sudo().create({
                        'name': company_name
                    })

                exp_record = request.env['hr.applicant.experience'].sudo().create({
                    'applicant_id': applicant.id,
                    'company_name': company.id,
                    'years': exp.get('years', 0),

                    'experience_certificate':
                        (exp.get('experience_certificate') or {}).get('data'),

                    'experience_certificate_filename':
                        (exp.get('experience_certificate') or {}).get('name'),

                    'joining_letter':
                        (exp.get('joining_letter') or {}).get('data'),

                    'joining_letter_filename':
                        (exp.get('joining_letter') or {}).get('name'),

                    'relieving_letter':
                        (exp.get('relieving_letter') or {}).get('data'),

                    'relieving_letter_filename':
                        (exp.get('relieving_letter') or {}).get('name'),

                    'other_certificate':
                        (exp.get('other_certificate') or {}).get('data'),

                    'other_certificate_filename':
                        (exp.get('other_certificate') or {}).get('name'),
                })

                # Bank Statement
                bank_attachment_id = create_exp_attachment(
                    exp.get('bank_statement'),
                    exp_record
                )

                if bank_attachment_id:
                    exp_record.write({
                        'bank_statement_id': [(4, bank_attachment_id)]
                    })

                # Salary Slip
                salary_attachment_id = create_exp_attachment(
                    exp.get('salary_slip'),
                    exp_record
                )

                if salary_attachment_id:
                    exp_record.write({
                        'salary_slip_id': [(4, salary_attachment_id)]
                    })

            # ==========================================
            # MARK AS SUBMITTED
            # ==========================================
            applicant.write({
                'is_application_submitted': True
            })

            return {
                "status": "success",
                "message": "Application submitted successfully",
                "applicant_id": applicant.id
            }

        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }

    @http.route('/api/applicant/list', type='jsonrpc', auth='public', methods=['POST'], csrf=False)
    def applicant_list(self, job_id=None):
        try:
            if not job_id:
                return {
                    "status": "error",
                    "message": "job_id is required"
                }
            job = request.env['hr.job'].sudo().browse(int(job_id))
            if not job.exists():
                return {
                    "status": "error",
                    "message": "Job position not found"
                }
            applicants = request.env['hr.applicant'].sudo().search([
                ('job_id', '=', job.id)
            ])
            result = []
            for rec in applicants:
                result.append({
                    "id": rec.id,
                    "applicant_name": rec.partner_name,
                    "email": rec.email_from,
                    "phone": rec.partner_phone,
                    "job_position": rec.job_id.name,
                })

            return {
                "status": "success",
                "message": "Applicants fetched successfully",
                "job_position": job.name,
                "total_applicants": len(result),
                "data": result
            }

        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }
