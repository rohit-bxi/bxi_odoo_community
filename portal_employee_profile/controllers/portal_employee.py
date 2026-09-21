# -*- coding: utf-8 -*-

from odoo import http, fields
from odoo.http import request
import base64
import logging
_logger = logging.getLogger(__name__)



class EmployeePortal(http.Controller):

    def _get_employee(self):
        user = request.env.user
        if user.employee_id:
            return user.employee_id
        # Fallback search by user_id or email
        return request.env['hr.employee'].sudo().search([
            '|', ('user_id', '=', user.id),
            '|', ('work_email', '=', user.email), ('private_email', '=', user.email)
        ], limit=1)

    @http.route(['/my/payslips', '/my/payslip'], type='http', auth='user', website=True, sitemap=False)
    def my_payslips(self, month=None, year=None, **kw):
        employee = self._get_employee()
        today = fields.Date.today()

        # Selected or default month/year
        selected_month = int(month) if month and str(month).isdigit() else today.month
        selected_year = int(year) if year and str(year).isdigit() else today.year

        payslip = False
        if employee:
            # Search for payslips of this employee
            all_slips = request.env['hr.payslip'].sudo().search([
                ('employee_id', '=', employee.id),
                ('state', 'in', ['done', 'paid', 'verify']),
            ], order='date_to desc')

            # Find slip matching selected month and year
            for slip in all_slips:
                if slip.date_to and slip.date_to.month == selected_month and slip.date_to.year == selected_year:
                    payslip = slip
                    break
                elif slip.date_from and slip.date_from.month == selected_month and slip.date_from.year == selected_year:
                    payslip = slip
                    break

        months_list = [
            (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
            (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
            (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December')
        ]

        years_list = list(range(today.year - 5, today.year + 2))

        return request.render(
            'portal_employee_profile.portal_my_payslips',
            {
                'employee': employee,
                'payslip': payslip,
                'docs': payslip,
                'selected_month': selected_month,
                'selected_year': selected_year,
                'months_list': months_list,
                'years_list': years_list,
            }
        )

    DOCUMENT_FIELDS = [
        'adhar_card_front',
        'adhar_card_back',
        'pan_number_proof',
        'doc_10th_id',
        'doc_12th_id',
        'doc_graduation_id',
        'doc_master_id',
        'any_certificate',
        'photograph',
        'data_privacy_doc',
        'data_security_doc',
        'passport_doc',
    ]

    EXPERIENCE_DOCUMENT_FIELDS = [
        'bank_statement_id',
        'salary_slip_id',
        'experience_certificate',
        'joining_letter',
        'relieving_letter',
        'other_certificate',
    ]

    def _get_employee(self):
        user = request.env.user

        # First preference: employee linked directly with user
        if user.employee_id:
            return user.employee_id

        # Fallback
        employee = request.env['hr.employee'].sudo().search([
            '|',
            ('user_id', '=', user.id),
            '|',
            ('work_email', '=', user.email),
            ('private_email', '=', user.email),
        ], limit=1)

        return employee


    @http.route([
        '/my/employee-profile',
        '/my/employee_profile',
        '/my/employee/profile',
        '/employee/profile',
        '/employee-profile',
    ], type='http', auth='user', website=True, sitemap=False)
    def employee_profile(self, **kw):

        employee = self._get_employee()

        countries = request.env[
            'res.country'
        ].sudo().search([])

        document_data = {}
        experiences = []

        if employee:
            document_data = self._get_employee_documents(
                employee
            )
            experiences = self._get_employee_experiences(
                employee
            )

        return request.render(
            'portal_employee_profile.portal_employee_profile',
            {
                'employee': employee,
                'countries': countries,
                'document_data': document_data,
                'experiences': experiences,
            }
        )

    # ============================================================
    # GET EMPLOYEE DOCUMENTS
    # ============================================================

    def _get_employee_documents(self, employee):

        documents = {}

        for field_name in self.DOCUMENT_FIELDS:

            documents[field_name] = []

            if field_name not in employee._fields:
                continue

            attachments = employee.sudo()[field_name]

            for attachment in attachments:

                documents[field_name].append({
                    'id': attachment.id,
                    'name': attachment.name,
                    'mimetype': attachment.mimetype,
                    'file_size': attachment.file_size,
                    'url': (
                        '/web/content/%s'
                        % attachment.id
                    ),
                    'download_url': (
                        '/web/content/%s?download=true'
                        % attachment.id
                    ),
                })

        return documents

    # ============================================================
    # GET EMPLOYEE EXPERIENCES
    # ============================================================

    def _get_employee_experiences(self, employee):

        experiences = []

        Experience = request.env[
            'hr.experience.employee'
        ].sudo()

        employee_experiences = Experience.search(
            [
                ('employee_id', '=', employee.id),
            ],
            order='id asc',
        )

        for index, experience in enumerate(employee_experiences):

            documents = {}

            for field_name in self.EXPERIENCE_DOCUMENT_FIELDS:

                documents[field_name] = []

                if field_name not in experience._fields:
                    continue

                attachments = experience[field_name]

                for attachment in attachments:

                    documents[field_name].append({
                        'id': attachment.id,
                        'name': attachment.name,
                        'mimetype': attachment.mimetype,
                        'file_size': attachment.file_size,
                        'url': (
                            '/web/content/%s'
                            % attachment.id
                        ),
                        'download_url': (
                            '/web/content/%s?download=true'
                            % attachment.id
                        ),
                    })

            experiences.append({
                'index': index,
                'id': experience.id,
                'company_name': experience.company_name or '',
                'years': experience.years or 0,
                'documents': documents,
            })

        return experiences
    # ============================================================
    # UPLOAD EMPLOYEE DOCUMENT
    # ============================================================

    def _upload_employee_document(
        self,
        employee,
        field_name,
        uploaded_file
    ):

        if not uploaded_file:
            return False

        if not uploaded_file.filename:
            return False

        file_data = uploaded_file.read()

        if not file_data:
            return False

        if field_name not in employee._fields:
            _logger.warning(
                'Employee field does not exist: %s',
                field_name,
            )
            return False

        Attachment = request.env[
            'ir.attachment'
        ].sudo()

        existing_attachments = employee.sudo()[field_name]

        # Remove old attachment only when a new
        # attachment is actually uploaded.
        if existing_attachments:

            employee.sudo().write({
                field_name: [(5, 0, 0)],
            })

            existing_attachments.sudo().unlink()

        attachment = Attachment.create({
            'name': uploaded_file.filename,
            'type': 'binary',
            'datas': base64.b64encode(file_data),
            'res_model': 'hr.employee',
            'res_id': employee.id,
        })

        employee.sudo().write({
            field_name: [(4, attachment.id)],
        })

        return attachment

    # ============================================================
    # UPLOAD EXPERIENCE DOCUMENTS
    # ============================================================

    def _upload_experience_documents(
        self,
        experience,
        field_name,
        uploaded_files
    ):

        if not uploaded_files:
            return

        if field_name not in experience._fields:
            _logger.warning(
                'Experience field does not exist: %s',
                field_name,
            )
            return

        # Remove empty file objects.
        valid_files = [
            uploaded_file
            for uploaded_file in uploaded_files
            if uploaded_file
            and uploaded_file.filename
        ]

        if not valid_files:
            return

        Attachment = request.env[
            'ir.attachment'
        ].sudo()

        existing_attachments = experience.sudo()[field_name]

        # Replace existing documents only when
        # a new document has actually been uploaded.
        if existing_attachments:

            experience.sudo().write({
                field_name: [(5, 0, 0)],
            })

            existing_attachments.sudo().unlink()

        attachment_ids = []

        for uploaded_file in valid_files:

            file_data = uploaded_file.read()

            if not file_data:
                continue

            attachment = Attachment.create({
                'name': uploaded_file.filename,
                'type': 'binary',
                'datas': base64.b64encode(file_data),
                'res_model': 'hr.experience.employee',
                'res_id': experience.id,
            })

            attachment_ids.append(
                attachment.id
            )

        if attachment_ids:

            experience.sudo().write({
                field_name: [
                    (6, 0, attachment_ids)
                ],
            })

    # ============================================================
    # PROFILE UPDATE
    # ============================================================

    @http.route([
        '/my/employee-profile/update',
        '/my/employee_profile/update',
    ], type='http', auth='user', methods=['POST'],
       website=True, csrf=True)
    def employee_profile_update(self, **post):

        employee = self._get_employee()

        if not employee:
            return request.redirect(
                '/my/employee-profile'
            )

        vals = {}

        # ========================================================
        # PERSONAL
        # ========================================================

        if 'name' in post:

            name_val = post.get('name') or False

            if 'name' in employee._fields:
                vals['name'] = name_val

            if 'legal_name' in employee._fields:
                vals['legal_name'] = name_val

        if 'private_email' in post:

            if 'private_email' in employee._fields:
                vals['private_email'] = (
                    post.get('private_email') or False
                )

        if 'work_email' in post:

            if 'work_email' in employee._fields:
                vals['work_email'] = (
                    post.get('work_email') or False
                )

        if 'private_phone' in post:

            phone_val = (
                post.get('private_phone') or False
            )

            if 'private_phone' in employee._fields:
                vals['private_phone'] = phone_val

            if 'work_phone' in employee._fields:
                vals['work_phone'] = phone_val

        if 'birthday' in post:

            if 'birthday' in employee._fields:
                vals['birthday'] = (
                    post.get('birthday') or False
                )

        if 'aadhar_card' in post:

            if 'aadhar_card' in employee._fields:
                vals['aadhar_card'] = (
                    post.get('aadhar_card') or False
                )

        if 'role_band' in post:

            if 'role_band' in employee._fields:
                vals['role_band'] = (
                    post.get('role_band') or False
                )

        if 'country_id' in post:

            country_id = post.get('country_id')

            if 'country_id' in employee._fields:

                vals['country_id'] = (
                    int(country_id)
                    if country_id
                    and str(country_id).isdigit()
                    else False
                )

        # ========================================================
        # EMERGENCY
        # ========================================================

        if 'emergency_contact' in post:

            if 'emergency_contact' in employee._fields:
                vals['emergency_contact'] = (
                    post.get('emergency_contact') or False
                )

        if 'emergency_phone' in post:

            if 'emergency_phone' in employee._fields:
                vals['emergency_phone'] = (
                    post.get('emergency_phone') or False
                )

        if 'l10n_in_relationship' in post:

            if 'l10n_in_relationship' in employee._fields:
                vals['l10n_in_relationship'] = (
                    post.get('l10n_in_relationship') or False
                )

        # ========================================================
        # CITIZENSHIP
        # ========================================================

        if 'is_non_resident' in post:

            if 'is_non_resident' in employee._fields:
                vals['is_non_resident'] = bool(
                    post.get('is_non_resident')
                )

        if 'passport_number' in post:

            if 'passport_number' in employee._fields:
                vals['passport_number'] = (
                    post.get('passport_number') or False
                )

        # ========================================================
        # BANK DOCUMENT
        # ========================================================

        uploaded_bank_file = (
            request.httprequest.files.get(
                'bank_document'
            )
        )

        if (
            uploaded_bank_file
            and uploaded_bank_file.filename
        ):

            bank_file_data = (
                uploaded_bank_file.read()
            )

            if bank_file_data:

                if 'bank_document' in employee._fields:

                    vals['bank_document'] = (
                        base64.b64encode(
                            bank_file_data
                        )
                    )

                if (
                    'bank_document_filename'
                    in employee._fields
                ):

                    vals[
                        'bank_document_filename'
                    ] = uploaded_bank_file.filename

        # ========================================================
        # MARITAL
        # ========================================================

        if 'marital' in post:

            if 'marital' in employee._fields:
                vals['marital'] = (
                    post.get('marital') or False
                )

        if 'children' in post:

            children_val = post.get('children')

            try:

                vals['children'] = (
                    int(children_val)
                    if children_val
                    and str(children_val).isdigit()
                    else 0
                )

            except (
                ValueError,
                TypeError,
            ):

                vals['children'] = 0

        # ========================================================
        # DISABLED
        # ========================================================

        if 'disabled' in post:

            if 'disabled' in employee._fields:
                vals['disabled'] = bool(
                    post.get('disabled')
                )

        # ========================================================
        # ADDRESS
        # ========================================================

        if 'private_street' in post:

            if 'private_street' in employee._fields:
                vals['private_street'] = (
                    post.get('private_street') or False
                )

        if 'private_street2' in post:

            if 'private_street2' in employee._fields:
                vals['private_street2'] = (
                    post.get('private_street2') or False
                )

        if 'city' in post:

            if 'private_city' in employee._fields:
                vals['private_city'] = (
                    post.get('city') or False
                )

        if 'zip' in post:

            if 'private_zip' in employee._fields:
                vals['private_zip'] = (
                    post.get('zip') or False
                )

        # ========================================================
        # GOVERNMENT INFORMATION
        # ========================================================

        if 'l10n_in_uan' in post:

            if 'l10n_in_uan' in employee._fields:
                vals['l10n_in_uan'] = (
                    post.get('l10n_in_uan') or False
                )

        if 'l10n_in_esic_number' in post:

            if 'l10n_in_esic_number' in employee._fields:
                vals['l10n_in_esic_number'] = (
                    post.get('l10n_in_esic_number') or False
                )

        if 'l10n_in_pan' in post:

            if 'l10n_in_pan' in employee._fields:
                vals['l10n_in_pan'] = (
                    post.get('l10n_in_pan') or False
                )

        if 'medical_insurance_no' in post:

            if 'medical_insurance_no' in employee._fields:
                vals['medical_insurance_no'] = (
                    post.get('medical_insurance_no') or False
                )

        # ========================================================
        # BANK INFORMATION
        # ========================================================

        if 'bank_ifsc' in post:

            if 'bank_ifsc' in employee._fields:
                vals['bank_ifsc'] = (
                    post.get('bank_ifsc') or False
                )

        if 'bank_name' in post:

            if 'bank_name' in employee._fields:
                vals['bank_name'] = (
                    post.get('bank_name') or False
                )

        if 'bank_account_number' in post:

            if 'bank_account_number' in employee._fields:
                vals['bank_account_number'] = (
                    post.get('bank_account_number') or False
                )

        # ========================================================
        # SAVE EMPLOYEE PROFILE
        # ========================================================

        if vals:

            employee.sudo().write(vals)

        # ========================================================
        # EMPLOYEE DOCUMENTS
        # ========================================================

        for field_name in self.DOCUMENT_FIELDS:

            uploaded_document = (
                request.httprequest.files.get(
                    field_name
                )
            )

            # No new file:
            # existing document remains unchanged.
            if (
                not uploaded_document
                or not uploaded_document.filename
            ):
                continue

            try:

                self._upload_employee_document(
                    employee,
                    field_name,
                    uploaded_document,
                )

            except Exception:

                _logger.exception(
                    'Error uploading employee '
                    'document: %s',
                    field_name,
                )

                return request.redirect(
                    '/my/employee-profile'
                    '?document_error=1'
                )

        # ========================================================
        # EMPLOYEE EXPERIENCE
        # ========================================================

        Experience = request.env[
            'hr.experience.employee'
        ].sudo()

        experience_index = 0

        while True:

            company_name = post.get(
                'experience_company_name_%s'
                % experience_index
            )

            years_value = post.get(
                'experience_years_%s'
                % experience_index
            )

            experience_id = post.get(
                'experience_id_%s'
                % experience_index
            )

            # Check whether this experience row exists.
            has_experience_data = (
                company_name
                or years_value
                or experience_id
            )

            if not has_experience_data:
                break

            # ----------------------------------------------------
            # Parse years
            # ----------------------------------------------------

            try:

                years = float(
                    years_value
                    or 0
                )

            except (
                ValueError,
                TypeError,
            ):

                years = 0.0

            experience = False

            # ----------------------------------------------------
            # Existing Experience
            # ----------------------------------------------------

            if experience_id:

                try:

                    experience_id_int = int(
                        experience_id
                    )

                except (
                    ValueError,
                    TypeError,
                ):

                    experience_id_int = False

                if experience_id_int:

                    experience = Experience.search(
                        [
                            ('id', '=', experience_id_int),
                            (
                                'employee_id',
                                '=',
                                employee.id,
                            ),
                        ],
                        limit=1,
                    )

            # ----------------------------------------------------
            # Update Existing / Create New
            # ----------------------------------------------------

            if experience:

                experience.write({
                    'company_name': (
                        company_name or False
                    ),
                    'years': years,
                })

            else:

                experience = Experience.create({
                    'employee_id': employee.id,
                    'company_name': (
                        company_name or False
                    ),
                    'years': years,
                })

            # ----------------------------------------------------
            # Experience Documents
            # ----------------------------------------------------

            for field_name in (
                self.EXPERIENCE_DOCUMENT_FIELDS
            ):

                input_name = (
                    '%s_%s'
                    % (
                        field_name,
                        experience_index,
                    )
                )

                uploaded_files = (
                    request.httprequest.files.getlist(
                        input_name
                    )
                )

                valid_files = [
                    uploaded_file
                    for uploaded_file in uploaded_files
                    if uploaded_file
                    and uploaded_file.filename
                ]

                if not valid_files:
                    continue

                try:

                    self._upload_experience_documents(
                        experience,
                        field_name,
                        valid_files,
                    )

                except Exception:

                    _logger.exception(
                        'Error uploading experience '
                        'document. Field: %s, '
                        'Experience: %s',
                        field_name,
                        experience.id,
                    )

                    return request.redirect(
                        '/my/employee-profile'
                        '?document_error=1'
                    )

            experience_index += 1

        # ========================================================
        # SUCCESS
        # ========================================================

        return request.redirect(
            '/my/employee-profile'
            '?profile_updated=1'
        )

    # ============================================================
    # REMOVE EMPLOYEE DOCUMENT
    # ============================================================

    @http.route(
        '/my/employee-profile/document/remove',
        type='http',
        auth='user',
        website=True,
        methods=['GET'],
        csrf=False,
    )
    def remove_employee_document(
        self,
        field=None,
        **kw
    ):

        employee = self._get_employee()

        if not employee:
            return request.redirect(
                '/my/employee-profile'
            )

        # --------------------------------------------------------
        # Bank Document
        # --------------------------------------------------------

        if field == 'bank_document':

            vals = {}

            if 'bank_document' in employee._fields:
                vals['bank_document'] = False

            if (
                'bank_document_filename'
                in employee._fields
            ):
                vals[
                    'bank_document_filename'
                ] = False

            if vals:
                employee.sudo().write(vals)

            return request.redirect(
                '/my/employee-profile'
            )

        # --------------------------------------------------------
        # Employee Documents
        # --------------------------------------------------------

        if field not in self.DOCUMENT_FIELDS:

            return request.redirect(
                '/my/employee-profile'
            )

        if field not in employee._fields:

            return request.redirect(
                '/my/employee-profile'
            )

        attachments = employee.sudo()[field]

        if attachments:

            employee.sudo().write({
                field: [(5, 0, 0)],
            })

            attachments.sudo().unlink()

        return request.redirect(
            '/my/employee-profile'
        )

    # ============================================================
    # REMOVE EXPERIENCE DOCUMENT
    # ============================================================

    @http.route(
        '/my/employee-profile/experience/document/remove',
        type='http',
        auth='user',
        website=True,
        methods=['GET'],
        csrf=False,
    )
    def remove_experience_document(
        self,
        experience_id=None,
        field=None,
        **kw
    ):

        employee = self._get_employee()

        if not employee:
            return request.redirect(
                '/my/employee-profile'
            )

        # --------------------------------------------------------
        # Validate field
        # --------------------------------------------------------

        if field not in self.EXPERIENCE_DOCUMENT_FIELDS:

            return request.redirect(
                '/my/employee-profile'
            )

        if not experience_id:

            return request.redirect(
                '/my/employee-profile'
            )

        # --------------------------------------------------------
        # Validate experience ID
        # --------------------------------------------------------

        try:

            experience_id = int(
                experience_id
            )

        except (
            ValueError,
            TypeError,
        ):

            return request.redirect(
                '/my/employee-profile'
            )

        # --------------------------------------------------------
        # Get only current employee's experience
        # --------------------------------------------------------

        Experience = request.env[
            'hr.experience.employee'
        ].sudo()

        experience = Experience.search(
            [
                ('id', '=', experience_id),
                (
                    'employee_id',
                    '=',
                    employee.id,
                ),
            ],
            limit=1,
        )

        if not experience:

            return request.redirect(
                '/my/employee-profile'
            )

        # --------------------------------------------------------
        # Remove attachment
        # --------------------------------------------------------

        if field not in experience._fields:

            return request.redirect(
                '/my/employee-profile'
            )

        attachments = experience[field]

        if attachments:

            experience.sudo().write({
                field: [(5, 0, 0)],
            })

            attachments.sudo().unlink()

        return request.redirect(
            '/my/employee-profile'
        )

    # ============================================================
    # REMOVE COMPLETE EXPERIENCE RECORD
    # ============================================================

    @http.route(
        '/my/employee-profile/experience/remove',
        type='http',
        auth='user',
        website=True,
        methods=['GET'],
        csrf=False,
    )
    def remove_experience(
        self,
        experience_id=None,
        **kw
    ):

        employee = self._get_employee()

        if not employee:
            return request.redirect(
                '/my/employee-profile'
            )

        if not experience_id:
            return request.redirect(
                '/my/employee-profile'
            )

        try:

            experience_id = int(
                experience_id
            )

        except (
            ValueError,
            TypeError,
        ):

            return request.redirect(
                '/my/employee-profile'
            )

        Experience = request.env[
            'hr.experience.employee'
        ].sudo()

        experience = Experience.search(
            [
                ('id', '=', experience_id),
                (
                    'employee_id',
                    '=',
                    employee.id,
                ),
            ],
            limit=1,
        )

        if not experience:
            return request.redirect(
                '/my/employee-profile'
            )

        # Delete all experience attachments first.
        for field_name in (
            self.EXPERIENCE_DOCUMENT_FIELDS
        ):

            if field_name not in experience._fields:
                continue

            attachments = experience[field_name]

            if attachments:

                experience.sudo().write({
                    field_name: [(5, 0, 0)],
                })

                attachments.sudo().unlink()

        experience.unlink()

        return request.redirect(
            '/my/employee-profile'
        )