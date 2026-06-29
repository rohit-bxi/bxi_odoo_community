from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError



class TravelRequest(http.Controller):

    @http.route(['/my/travel-request'], type='http', auth='user', website=True)
    def travel_request(self, **kwargs):
        user = request.env.user
        T_Request = request.env['travel.request'].sudo()
        if user.has_group('base.group_user'):
            t_request = T_Request.search([])
        else:
            employee = request.env['hr.employee'].sudo().search([
                ('user_id', '=', user.id)
            ], limit=1)
            t_request = []
            if employee:
                t_request = T_Request.search([
                    ('employee_id', '=', employee.id)
                ])
        values = {
            'requests': t_request,
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