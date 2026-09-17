from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import pager as portal_pager


class PerformanceBonusPortal(http.Controller):

    @http.route(
        ['/my/performance-bonus-letters',
         '/my/performance-bonus-letters/page/<int:page>'],
        type='http', auth='user', website=True
    )
    def portal_performance_bonus_letters(self, page=1, **kwargs):
        user = request.env.user
        Appraisal = request.env['hr.employee.appraisal'].sudo()

        # Find employee linked to current user by user_id or email
        employees = request.env['hr.employee'].sudo().search([
            '|', ('user_id', '=', user.id),
            ('work_email', '=ilike', user.email or user.login)
        ])
        emp_ids = employees.ids

        if emp_ids:
            domain = [
                ('employee_id', 'in', emp_ids),
                ('state', '=', 'released'),
            ]
        else:
            domain = [('id', '=', 0)]  # Return nothing if no employee linked

        letter_count = Appraisal.search_count(domain)

        pager = portal_pager(
            url='/my/performance-bonus-letters',
            total=letter_count,
            page=page,
            step=10
        )

        letters = Appraisal.search(
            domain,
            order='release_date desc, id desc',
            limit=10,
            offset=pager['offset']
        )

        # Friendly labels for letter types
        letter_type_labels = {
            'bonus_letter': 'Bonus Letter',
            'appraisal_promotion_letter': 'Appraisal & Promotion Letter',
            'appraisal_letter': 'Appraisal Letter',
            'promotion_letter': 'Promotion Letter',
        }

        values = {
            'letters': letters,
            'page_name': 'performance_bonus_letters',
            'pager': pager,
            'letter_type_labels': letter_type_labels,
        }
        return request.render(
            'bxi_hr_performance_bonus.portal_my_performance_bonus_letters', values
        )

    @http.route(
        '/my/performance-bonus-letters/<int:letter_id>',
        type='http', auth='user', website=True
    )
    def portal_performance_bonus_letter_detail(self, letter_id, **kwargs):
        user = request.env.user
        Appraisal = request.env['hr.employee.appraisal'].sudo()

        # Find employee linked to current user
        employees = request.env['hr.employee'].sudo().search([
            '|', ('user_id', '=', user.id),
            ('work_email', '=ilike', user.email or user.login)
        ])
        emp_ids = employees.ids

        letter = Appraisal.search([
            ('id', '=', letter_id),
            ('employee_id', 'in', emp_ids),
            ('state', '=', 'released'),
        ], limit=1)

        if not letter:
            return request.redirect('/my/performance-bonus-letters')

        # Map letter_type to the corresponding report action XML ID for PDF download
        report_map = {
            'bonus_letter': 'bxi_hr_performance_bonus.action_report_employee_bonus_letter',
            'appraisal_letter': 'bxi_hr_performance_bonus.action_report_appraisal_letter',
            'appraisal_promotion_letter': 'bxi_hr_performance_bonus.action_report_appraisal_letter',
            'promotion_letter': 'bxi_hr_performance_bonus.action_report_promotion_letter',
        }

        # Map letter_type to the report name for the PDF URL
        report_name_map = {
            'bonus_letter': 'bxi_hr_performance_bonus.report_employee_bonus_letter',
            'appraisal_letter': 'bxi_hr_performance_bonus.report_appraisal_letter_template',
            'appraisal_promotion_letter': 'bxi_hr_performance_bonus.report_appraisal_letter_template',
            'promotion_letter': 'bxi_hr_performance_bonus.report_promotion_letter_template',
        }

        letter_type_labels = {
            'bonus_letter': 'Bonus Letter',
            'appraisal_promotion_letter': 'Appraisal & Promotion Letter',
            'appraisal_letter': 'Appraisal Letter',
            'promotion_letter': 'Promotion Letter',
        }

        report_name = report_name_map.get(letter.letter_type, '')
        pdf_url = '/report/pdf/%s/%s' % (report_name, letter.id) if report_name else ''

        values = {
            'letter': letter,
            'o': letter,
            'page_name': 'performance_bonus_letter_detail',
            'letter_type_labels': letter_type_labels,
            'pdf_url': pdf_url,
        }
        return request.render(
            'bxi_hr_performance_bonus.portal_performance_bonus_letter_detail', values
        )
