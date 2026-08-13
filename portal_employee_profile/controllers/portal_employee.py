# -*- coding: utf-8 -*-

from odoo import http, fields
from odoo.http import request
import base64


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

    @http.route([
        '/my/employee-profile',
        '/my/employee_profile',
        '/my/employee/profile',
        '/employee/profile',
        '/employee-profile'
    ], type='http', auth='user', website=True, sitemap=False)
    def employee_profile(self, **kw):
        employee = self._get_employee()
        countries = request.env['res.country'].sudo().search([])

        return request.render(
            'portal_employee_profile.portal_employee_profile',
            {
                'employee': employee,
                'countries': countries,
            }
        )

    @http.route([
        '/my/employee-profile/update',
        '/my/employee_profile/update'
    ], type='http', auth='user', methods=['POST'], website=True, csrf=True)
    def employee_profile_update(self, **post):

        employee = self._get_employee()
        if not employee:
            return request.redirect('/my/employee-profile')

        vals = {}

        # ================= PERSONAL =================
        if 'name' in post:
            name_val = post.get('name') or False
            vals['name'] = name_val
            if 'legal_name' in employee._fields:
                vals['legal_name'] = name_val

        if 'private_email' in post:
            vals['private_email'] = post.get('private_email') or False

        if 'work_email' in post:
            vals['work_email'] = post.get('work_email') or False

        if 'private_phone' in post:
            phone_val = post.get('private_phone') or False
            vals['private_phone'] = phone_val
            if 'work_phone' in employee._fields:
                vals['work_phone'] = phone_val

        if 'birthday' in post:
            vals['birthday'] = post.get('birthday') or False

        if 'aadhar_card' in post:
            vals['aadhar_card'] = post.get('aadhar_card') or False

        if 'role_band' in post:
            vals['role_band'] = post.get('role_band') or False

        if 'country_id' in post:
            country_id = post.get('country_id')
            vals['country_id'] = int(country_id) if country_id and str(country_id).isdigit() else False

        # ================= EMERGENCY =================
        if 'emergency_contact' in post:
            vals['emergency_contact'] = post.get('emergency_contact') or False

        if 'emergency_phone' in post:
            vals['emergency_phone'] = post.get('emergency_phone') or False

        if 'l10n_in_relationship' in post:
            vals['l10n_in_relationship'] = post.get('l10n_in_relationship') or False

        # ================= CITIZENSHIP =================
        vals['is_non_resident'] = bool(post.get('is_non_resident'))

        if 'passport_id' in post:
            vals['passport_id'] = post.get('passport_id') or False

        uploaded_file = request.httprequest.files.get('bank_document')
        if uploaded_file and uploaded_file.filename:
            file_data = uploaded_file.read()
            if file_data:
                vals['bank_document'] = base64.b64encode(file_data)

        if 'marital' in post:
            vals['marital'] = post.get('marital') or False

        if 'children' in post:
            children_val = post.get('children')
            try:
                vals['children'] = int(children_val) if children_val and str(children_val).isdigit() else 0
            except:
                vals['children'] = 0

        vals['disabled'] = bool(post.get('disabled'))

        # ================= ADDRESS =================
        if 'private_street' in post:
            vals['private_street'] = post.get('private_street') or False

        if 'private_street2' in post:
            vals['private_street2'] = post.get('private_street2') or False

        if 'city' in post:
            vals['private_city'] = post.get('city') or False

        if 'zip' in post:
            vals['private_zip'] = post.get('zip') or False

        # ================= GOV INFO =================
        if 'l10n_in_uan' in post:
            vals['l10n_in_uan'] = post.get('l10n_in_uan') or False

        if 'l10n_in_esic_number' in post:
            vals['l10n_in_esic_number'] = post.get('l10n_in_esic_number') or False

        if 'l10n_in_pan' in post:
            vals['l10n_in_pan'] = post.get('l10n_in_pan') or False

        if 'medical_insurance_no' in post:
            vals['medical_insurance_no'] = post.get('medical_insurance_no') or False

        if 'bank_ifsc' in post:
            vals['bank_ifsc'] = post.get('bank_ifsc') or False

        if 'bank_name' in post:
            vals['bank_name'] = post.get('bank_name') or False

        if 'bank_account_number' in post:
            vals['bank_account_number'] = post.get('bank_account_number') or False

        if vals:
            employee.sudo().write(vals)

        return request.redirect('/?profile_updated=1')
