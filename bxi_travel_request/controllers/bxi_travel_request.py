# -*- coding: utf-8 -*-
import json
import logging
from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class TravelRequestPortal(http.Controller):

    # ─── 1. List View (Employee / Manager / HR) ─────────────────────
    @http.route(['/my/travel-request'], type='http', auth='user', website=True)
    def travel_request_list(self, filter_type=None, **kwargs):
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        T_Request = request.env['travel.request'].sudo()

        is_hr = user.has_group('hr.group_hr_user') or user.has_group('hr.group_hr_manager') or user.has_group('base.group_system')
        is_manager = bool(employee and employee.child_ids)

        domain = [('company_id', 'in', request.env.companies.ids)]

        if filter_type == 'pending_approval':
            if is_hr:
                domain.append(('state', 'in', ('hr_approval', 'manager_approval')))
            elif is_manager:
                domain.extend([('state', '=', 'manager_approval'), ('employee_id.parent_id', '=', employee.id)])
            else:
                domain.append(('employee_id', '=', employee.id if employee else False))
        elif filter_type == 'team' and is_manager:
            domain.append(('employee_id.parent_id', '=', employee.id))
        elif filter_type == 'all' and is_hr:
            pass  # all requests in allowed companies
        else:
            # Default: employee's own requests
            if employee:
                domain.append(('employee_id', '=', employee.id))
            else:
                domain.append(('id', '=', 0))

        requests = T_Request.search(domain, order='id desc')

        # Count pending for badge counters
        pending_count = 0
        if is_hr:
            pending_count = T_Request.search_count([
                ('company_id', 'in', request.env.companies.ids),
                ('state', 'in', ('hr_approval', 'manager_approval'))
            ])
        elif is_manager:
            pending_count = T_Request.search_count([
                ('company_id', 'in', request.env.companies.ids),
                ('state', '=', 'manager_approval'),
                ('employee_id.parent_id', '=', employee.id)
            ])

        return request.render('bxi_travel_request.bxi_travel_request_template', {
            'requests': requests,
            'employee': employee,
            'is_hr': is_hr,
            'is_manager': is_manager,
            'filter_type': filter_type or 'my',
            'pending_count': pending_count,
        })

    # ─── 2. Submit Travel Request ──────────────────────────────────
    @http.route('/my/submit-travel-request', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def submit_request(self, **post):
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)

        # AJAX helper for state dropdown dependent on country selection
        country_id = request.params.get('country_id')
        if country_id:
            states = request.env['res.country.state'].sudo().search([('country_id', '=', int(country_id))])
            return request.make_json_response({
                'states': [{'id': s.id, 'name': s.name} for s in states]
            })

        india_id = request.env.ref('base.in').id

        def get_int(field, default=False):
            val = post.get(field)
            return int(val) if val and str(val).isdigit() else default

        def get_float(field, default=0.0):
            val = post.get(field)
            try:
                return float(val) if val else default
            except ValueError:
                return default

        from_country = get_int('from_country', india_id)
        to_country = get_int('to_country', india_id)
        state_model = request.env['res.country.state'].sudo()

        if request.httprequest.method == 'POST' and post.get('travel_purpose'):
            hotel_req = bool(post.get('hotel_required'))
            cab_req = bool(post.get('cab_required'))
            adv_req = bool(post.get('advance_required'))

            vals = {
                'employee_id': employee.id if employee else False,
                'manager_id': employee.parent_id.id if (employee and employee.parent_id) else False,
                'department_id': employee.department_id.id if (employee and employee.department_id) else False,
                'travel_purpose': post.get('travel_purpose'),
                'from_country': from_country,
                'to_country': to_country,
                'from_state': get_int('from_state'),
                'to_state': get_int('to_state'),
                'from_city': post.get('from_city'),
                'to_city': post.get('to_city'),
                'from_address': post.get('from_address'),
                'to_address': post.get('to_address'),
                'departure_date': post.get('departure_date'),
                'return_date': post.get('return_date') or False,
                'mode_of_travel': post.get('mode_of_travel'),
                'trip_type': post.get('trip_type', 'round_trip'),
                'travel_class': post.get('travel_class', 'economy'),
                'contact_number': post.get('contact_number'),
                'email': post.get('email'),
                'other_info': post.get('other_info'),
                # Hotel preferences
                'hotel_required': hotel_req,
                'hotel_city': post.get('hotel_city') or post.get('to_city') if hotel_req else False,
                'hotel_grade': post.get('hotel_grade', '3') if hotel_req else False,
                'hotel_checkin': post.get('hotel_checkin') or post.get('departure_date') if hotel_req else False,
                'hotel_checkout': post.get('hotel_checkout') or post.get('return_date') if hotel_req else False,
                'hotel_rooms': get_int('hotel_rooms', 1) if hotel_req else 1,
                # Cab preferences
                'cab_required': cab_req,
                'cab_type': post.get('cab_type', 'any') if cab_req else False,
                'cab_pickup': post.get('cab_pickup') if cab_req else False,
                'cab_dropoff': post.get('cab_dropoff') if cab_req else False,
                # Advance Payment
                'advance_required': adv_req,
                'advance_amount': get_float('advance_amount') if adv_req else 0.0,
                'advance_notes': post.get('advance_notes') if adv_req else False,
                'state': 'manager_approval',
            }

            rec = request.env['travel.request'].sudo().create(vals)

            # Auto-create a travel segment line based on primary travel selection
            if post.get('mode_of_travel'):
                request.env['travel.request.option'].sudo().create({
                    'travel_request_id': rec.id,
                    'option_type': post.get('mode_of_travel'),
                    'origin_code': post.get('from_city'),
                    'destination_code': post.get('to_city'),
                    'travel_class': post.get('travel_class', 'economy'),
                    'description': f"{post.get('mode_of_travel').capitalize()} from {post.get('from_city')} to {post.get('to_city')}",
                })

            if hotel_req:
                request.env['travel.request.option'].sudo().create({
                    'travel_request_id': rec.id,
                    'option_type': 'hotel',
                    'hotel_city': post.get('hotel_city') or post.get('to_city'),
                    'hotel_grade': post.get('hotel_grade', '3'),
                    'checkin_date': post.get('hotel_checkin') or post.get('departure_date'),
                    'checkout_date': post.get('hotel_checkout') or post.get('return_date'),
                    'rooms': get_int('hotel_rooms', 1),
                    'description': f"Hotel stay in {post.get('hotel_city') or post.get('to_city')}",
                })

            if cab_req:
                request.env['travel.request.option'].sudo().create({
                    'travel_request_id': rec.id,
                    'option_type': 'cab',
                    'cab_type': post.get('cab_type', 'any'),
                    'pickup_location': post.get('cab_pickup'),
                    'drop_location': post.get('cab_dropoff'),
                    'description': f"Cab service in {post.get('to_city')}",
                })

            rec._send_state_email()
            return request.redirect(f'/my/travel-request/{rec.id}?success=1')

        return request.render('bxi_travel_request.submit_travel_template', {
            'employee': employee,
            'countries': request.env['res.country'].sudo().search([]),
            'from_country_id': from_country,
            'to_country_id': to_country,
            'from_states': state_model.search([('country_id', '=', from_country)]),
            'to_states': state_model.search([('country_id', '=', to_country)]),
            'mode_options': request.env['travel.request']._fields['mode_of_travel'].selection,
            'trip_options': request.env['travel.request']._fields['trip_type'].selection,
            'class_options': request.env['travel.request']._fields['travel_class'].selection,
            'hotel_grade_options': request.env['travel.request']._fields['hotel_grade'].selection,
            'cab_type_options': request.env['travel.request']._fields['cab_type'].selection,
        })

    # ─── 3. Detail View & Approval Actions ──────────────────────────
    @http.route(['/my/travel-request/<int:rec_id>'], type='http', auth='user', website=True)
    def travel_request_detail(self, rec_id, **kwargs):
        record = request.env['travel.request'].sudo().browse(rec_id)
        if not record.exists():
            return request.not_found()

        user = request.env.user
        current_emp = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)

        is_hr = user.has_group('hr.group_hr_user') or user.has_group('hr.group_hr_manager') or user.has_group('base.group_system')
        can_manager_approve = bool(
            record.state == 'manager_approval' and
            record.employee_id.parent_id and
            current_emp and
            record.employee_id.parent_id.id == current_emp.id
        )
        can_hr_approve = bool(record.state == 'hr_approval' and is_hr)

        return request.render('bxi_travel_request.travel_request_detail_template', {
            'record': record,
            'can_manager_approve': can_manager_approve,
            'can_hr_approve': can_hr_approve,
            'is_hr': is_hr,
            'success': kwargs.get('success'),
            'msg': kwargs.get('msg'),
        })

    # ─── 4. Website Manager Approval Action ────────────────────────
    @http.route('/my/travel-request/<int:rec_id>/approve-manager', type='http', auth='user', website=True, methods=['POST'])
    def manager_approve_website(self, rec_id, **kwargs):
        record = request.env['travel.request'].sudo().browse(rec_id)
        if record.exists():
            user = request.env.user
            current_emp = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
            if record.employee_id.parent_id and current_emp and record.employee_id.parent_id.id == current_emp.id:
                record.manager_action_approve()
                return request.redirect(f'/my/travel-request/{rec_id}?msg=Manager+Approved+Successfully')
        return request.redirect(f'/my/travel-request/{rec_id}')

    @http.route('/my/travel-request/<int:rec_id>/refuse-manager', type='http', auth='user', website=True, methods=['POST'])
    def manager_refuse_website(self, rec_id, **kwargs):
        record = request.env['travel.request'].sudo().browse(rec_id)
        if record.exists():
            user = request.env.user
            current_emp = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
            if record.employee_id.parent_id and current_emp and record.employee_id.parent_id.id == current_emp.id:
                record.manager_action_refuse()
                return request.redirect(f'/my/travel-request/{rec_id}?msg=Request+Refused')
        return request.redirect(f'/my/travel-request/{rec_id}')

    # ─── 5. Website HR Approval Action (Approve + Push to myBiz) ───
    @http.route('/my/travel-request/<int:rec_id>/approve-hr', type='http', auth='user', website=True, methods=['POST'])
    def hr_approve_website(self, rec_id, **kwargs):
        record = request.env['travel.request'].sudo().browse(rec_id)
        user = request.env.user
        is_hr = user.has_group('hr.group_hr_user') or user.has_group('hr.group_hr_manager') or user.has_group('base.group_system')
        if record.exists() and is_hr:
            record.hr_action_approve()
            return request.redirect(f'/my/travel-request/{rec_id}?msg=HR+Approved+and+Pushed+to+myBiz')
        return request.redirect(f'/my/travel-request/{rec_id}')

    @http.route('/my/travel-request/<int:rec_id>/refuse-hr', type='http', auth='user', website=True, methods=['POST'])
    def hr_refuse_website(self, rec_id, **kwargs):
        record = request.env['travel.request'].sudo().browse(rec_id)
        user = request.env.user
        is_hr = user.has_group('hr.group_hr_user') or user.has_group('hr.group_hr_manager') or user.has_group('base.group_system')
        if record.exists() and is_hr:
            record.hr_action_refuse()
            return request.redirect(f'/my/travel-request/{rec_id}?msg=Request+Refused+by+HR')
        return request.redirect(f'/my/travel-request/{rec_id}')