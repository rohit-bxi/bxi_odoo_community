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
        if post.get('name'):
            vals['name'] = post.get('name')
            vals['legal_name'] = post.get('name')

        if post.get('private_email'):
            vals['private_email'] = post.get('private_email')

        if post.get('work_email'):
            vals['work_email'] = post.get('work_email')

        if post.get('private_phone'):
            vals['private_phone'] = post.get('private_phone')
            vals['work_phone'] = post.get('private_phone')

        if post.get('birthday'):
            vals['birthday'] = post.get('birthday')

        if post.get('aadhar_card'):
            vals['aadhar_card'] = post.get('aadhar_card')

        if post.get('role_band'):
            vals['role_band'] = post.get('role_band')

        if post.get('country_id'):
            vals['country_id'] = int(post.get('country_id'))

        # ================= EMERGENCY =================
        if post.get('emergency_contact'):
            vals['emergency_contact'] = post.get('emergency_contact')

        if post.get('emergency_phone'):
            vals['emergency_phone'] = post.get('emergency_phone')

        if 'l10n_in_relationship' in employee._fields and post.get('l10n_in_relationship'):
            vals['l10n_in_relationship'] = post.get('l10n_in_relationship')

        # ================= CITIZENSHIP =================
        vals['is_non_resident'] = bool(post.get('is_non_resident'))

        if post.get('passport_id'):
            vals['passport_id'] = post.get('passport_id')

        uploaded_file = request.httprequest.files.get('bank_document')
        if uploaded_file:
            file_data = uploaded_file.read()
            vals['bank_document'] = base64.b64encode(file_data)

        if post.get('marital'):
            vals['marital'] = post.get('marital')

        if post.get('children'):
            try:
                vals['children'] = int(post.get('children'))
            except:
                pass

        vals['disabled'] = bool(post.get('disabled'))

        # ================= ADDRESS =================
        if post.get('private_street'):
            vals['private_street'] = post.get('private_street')

        if post.get('private_street2'):
            vals['private_street2'] = post.get('private_street2')

        if post.get('city'):
            vals['private_city'] = post.get('city')

        if post.get('zip'):
            vals['private_zip'] = post.get('zip')

        # ================= GOV INFO =================
        if post.get('l10n_in_uan'):
            vals['l10n_in_uan'] = post.get('l10n_in_uan')

        if post.get('l10n_in_esic_number'):
            vals['l10n_in_esic_number'] = post.get('l10n_in_esic_number')

        if post.get('l10n_in_pan'):
            vals['l10n_in_pan'] = post.get('l10n_in_pan')

        if post.get('medical_insurance_no'):
            vals['medical_insurance_no'] = post.get('medical_insurance_no')
        if post.get('bank_ifsc'):
            vals['bank_ifsc'] = post.get('bank_ifsc')
        if post.get('bank_name'):
            vals['bank_name'] = post.get('bank_name')

        if post.get('bank_account_number'):
            vals['bank_account_number'] = post.get('bank_account_number')
        
        if vals:
            employee.sudo().write(vals)

        return request.redirect('/?profile_updated=1')


    # @http.route(['/my/payslips'], type='http', auth='user', website=True)
    # def portal_my_payslips(self, **kw):
    #     employee = self._get_employee()

    #     if not employee:
    #         return request.redirect('/my/home')

    #     payslips = request.env['hr.payslip'].sudo().search(
    #         [('employee_id', '=', employee.id)],
    #         order='date_from desc'
    #     )

    #     return request.render(
    #         'portal_employee_profile.portal_my_payslips',
    #         {
    #             'payslips': payslips,
    #             'employee': employee,
    #         }
    #     )


    # @http.route(
    #     ['/my/payslip/<int:payslip_id>/download'],
    #     type='http',
    #     auth='user',
    #     website=True
    # )
    # def portal_download_payslip(self, payslip_id):

    #     payslip = request.env['hr.payslip'].sudo().browse(payslip_id)
    #     employee = self._get_employee()

    #     if not payslip.exists() or payslip.employee_id != employee:
    #         return request.redirect('/my')

    #     # XML ID of your custom report
    #     report_xmlid = 'custom_payslip_report.action_custom_payslip_pdf'

    #     report = request.env.ref(report_xmlid).sudo()

    #     pdf, _ = report._render_qweb_pdf(
    #         report_xmlid,
    #         res_ids=[payslip.id]
    #     )

    #     return request.make_response(
    #         pdf,
    #         headers=[
    #             ('Content-Type', 'application/pdf'),
    #             (
    #                 'Content-Disposition',
    #                 f'attachment; filename="Payslip-{payslip.name or payslip.id}.pdf"'
    #             ),
    #         ]
    #     )

