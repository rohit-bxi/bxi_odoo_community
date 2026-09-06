from odoo import http, fields as odoo_fields
from odoo.http import request
from odoo.exceptions import AccessError


class TravelRequest(http.Controller):

    @http.route(['/my/travel-request'], type='http', auth='user', website=True)
    def travel_request(self, **kwargs):
        user = request.env.user
        T_Request = request.env['travel.request'].sudo()

        current_employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', user.id)
        ], limit=1)

        self_requests = T_Request.browse()
        team_requests = T_Request.browse()

        if current_employee:
            self_requests = T_Request.search([
                ('employee_id', '=', current_employee.id)
            ])
            team_requests = T_Request.search([
                ('employee_id.parent_id', '=', current_employee.id)
            ])

        values = {
            'self_requests': self_requests,
            'team_requests': team_requests,
            'is_manager': bool(team_requests),
            'current_employee_id': current_employee.id if current_employee else False,
        }
        return request.render('bxi_travel_request.bxi_travel_request_template', values)

    @http.route('/my/submit-travel-request', type='http', auth="user", website=True, methods=['GET', 'POST'])
    def submit_request(self, **post):
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([
                ('user_id', '=', user.id)
            ], limit=1)
        
        country_id = request.params.get('country_id')
        if country_id:
            states = request.env['res.country.state'].sudo().search([
                ('country_id', '=', int(country_id))
            ])
            return request.make_json_response({
                'states': [{'id': s.id, 'name': s.name} for s in states]
            })
        india_id = request.env.ref('base.in').id

        def get_int(field, default):
            return int(post.get(field)) if post.get(field) else default

        from_country = get_int('from_country', india_id)
        to_country = get_int('to_country', india_id)
        state_model = request.env['res.country.state'].sudo()
        from_states = state_model.search([('country_id', '=', from_country)])
        to_states = state_model.search([('country_id', '=', to_country)])
        if request.httprequest.method == 'POST' and post.get('travel_purpose'):
            record = request.env['travel.request'].sudo().create({
                'name': 'New',
                'employee_id': employee.id,
                'manager_id': employee.parent_id.id if employee.parent_id else False,
                'department_id': employee.department_id.id if employee.department_id else False,
                'travel_purpose': post.get('travel_purpose'),
                'from_country': from_country,
                'to_country': to_country,
                'from_state': get_int('from_state', False),
                'to_state': get_int('to_state', False),
                'from_city': post.get('from_city'),
                'to_city': post.get('to_city'),
                'departure_date': post.get('departure_date'),
                'return_date': post.get('return_date'),
                'mode_of_travel': post.get('mode_of_travel'),
                'state': 'manager_approval',
            })
            record._send_state_email()
            
            return request.redirect(f'/my/travel-request/{record.id}')
        
        return request.render('bxi_travel_request.submit_travel_template', {
            'employee': employee,
            'countries': request.env['res.country'].sudo().search([]),
            'from_country_id': from_country,
            'to_country_id': to_country,
            'from_states': from_states,
            'to_states': to_states,
            'mode_options': request.env['travel.request']._fields['mode_of_travel'].selection,
        })

    @http.route(['/my/travel-request/<int:rec_id>'], type='http', auth='user', website=True)
    def travel_request_detail(self, rec_id):
        record = request.env['travel.request'].sudo().browse(rec_id)
        return request.render('bxi_travel_request.travel_request_detail_template', {
            'record': record
        })

    @http.route('/my/travel-request/approve', type='http', auth='user', website=True, methods=['POST'])
    def travel_request_approve(self, **post):
        rec_id = int(post.get('rec_id', 0))
        if not rec_id:
            return request.redirect('/my/travel-request')

        record = request.env['travel.request'].sudo().browse(rec_id)
        if not record.exists():
            return request.redirect('/my/travel-request')

        # Verify the logged-in user is the manager of that employee
        current_employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', request.env.user.id)
        ], limit=1)

        if (current_employee
                and record.employee_id.parent_id
                and record.employee_id.parent_id.id == current_employee.id
                and record.state == 'manager_approval'):
            # Manager identity already verified above; use sudo() to bypass
            # portal ACL (portal users don't have the 'Role / User' group).
            # Write directly so the correct manager employee is stamped,
            # not the sudo superuser.
            record.sudo().write({
                'state': 'hr_approval',
                'manager_approved_by': current_employee.id,
                'manager_approved_date': odoo_fields.Datetime.now(),
            })
            record.sudo()._send_state_email()

        return request.redirect('/my/travel-request')

    @http.route('/my/travel-request/reject', type='http', auth='user', website=True, methods=['POST'])
    def travel_request_reject(self, **post):
        rec_id = int(post.get('rec_id', 0))
        if not rec_id:
            return request.redirect('/my/travel-request')

        record = request.env['travel.request'].sudo().browse(rec_id)
        if not record.exists():
            return request.redirect('/my/travel-request')

        # Verify the logged-in user is the manager of that employee
        current_employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', request.env.user.id)
        ], limit=1)

        if (current_employee
                and record.employee_id.parent_id
                and record.employee_id.parent_id.id == current_employee.id
                and record.state == 'manager_approval'):
            # Manager identity already verified above; use sudo() to bypass
            # portal ACL.
            record.sudo().action_cancel()

        return request.redirect('/my/travel-request')