# -*- coding: utf-8 -*-
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class BxiMybizDashboard(models.AbstractModel):
    """
    Transient/helper model serving aggregated data for the myBiz Integration
    Dashboard OWL client action. Requires no DB table of its own.
    """
    _name = 'bxi.mybiz.dashboard'
    _description = 'myBiz Integration Dashboard API'

    @api.model
    def _get_scope_domain(self):
        user = self.env.user
        employee = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)

        is_admin = (
            user.has_group('bxi_travel_request.group_travel_admin')
            or user.has_group('base.group_system')
        )
        is_hr = user.has_group('hr.group_hr_user') or user.has_group('hr.group_hr_manager')
        is_manager = user.has_group('bxi_travel_request.group_travel_manager')

        domain = [('company_id', 'in', self.env.companies.ids)]
        if is_admin or is_hr:
            role = 'admin' if is_admin else 'hr'
        elif is_manager and employee:
            domain += ['|', ('employee_id.user_id', '=', user.id),
                       ('employee_id.parent_id.user_id', '=', user.id)]
            role = 'manager'
        elif employee:
            domain += [('employee_id', '=', employee.id)]
            role = 'employee'
        else:
            domain += [('id', '=', 0)]
            role = 'employee'

        return domain, {'is_admin': is_admin, 'is_hr': is_hr,
                        'is_manager': is_manager, 'role': role}

    @api.model
    def get_dashboard_data(self, days=90):
        TravelRequest = self.env['travel.request'].sudo()
        domain, roles = self._get_scope_domain()

        try:
            days = int(days)
        except (TypeError, ValueError):
            days = 90
        since = fields.Date.today() - timedelta(days=days)
        domain_recent = domain + [('request_date', '>=', since)]

        requests_recent = TravelRequest.search(domain_recent)

        state_selection = dict(TravelRequest._fields['state'].selection)
        mybiz_selection = dict(TravelRequest._fields['mybiz_status'].selection)

        state_counts = {key: 0 for key in state_selection}
        mybiz_counts = {key: 0 for key in mybiz_selection}
        for r in requests_recent:
            state_counts[r.state] = state_counts.get(r.state, 0) + 1
            mybiz_counts[r.mybiz_status] = mybiz_counts.get(r.mybiz_status, 0) + 1

        pushed = requests_recent.filtered(lambda r: r.mybiz_status != 'not_pushed')
        success_count = len(
            pushed.filtered(
                lambda r: r.mybiz_status in (
                    'pending',
                    'approved',
                    'booked')))
        failed_count = mybiz_counts.get('failed', 0)
        success_rate = round((success_count / len(pushed) * 100), 1) if pushed else 0.0

        pending_manager = TravelRequest.search_count(domain + [('state', '=', 'manager_approval')])
        pending_hr = TravelRequest.search_count(domain + [('state', '=', 'hr_approval')])
        mybiz_pending = TravelRequest.search_count(domain + [('state', '=', 'mybiz_pending')])

        upcoming = TravelRequest.search(
            domain + [('departure_date', '>=', fields.Date.today()), ('state', '=', 'approved')],
            order='departure_date', limit=8,
        )
        recent_failures = TravelRequest.search(
            domain + [('mybiz_status', '=', 'failed')],
            order='mybiz_sync_date desc', limit=8,
        )

        dept_spend = {}
        for r in requests_recent:
            dept = r.department_id.name or 'Unassigned'
            amount = (r.total_submitted_expense or 0.0) + (r.advance_amount or 0.0)
            dept_spend[dept] = dept_spend.get(dept, 0.0) + amount
        dept_spend_list = sorted(
            [{'department': k, 'amount': round(v, 2)} for k, v in dept_spend.items()],
            key=lambda d: d['amount'], reverse=True,
        )[:8]
        max_dept_amount = max([d['amount'] for d in dept_spend_list], default=0.0)

        months = []
        for i in range(5, -1, -1):
            month_start = (fields.Date.today() - relativedelta(months=i)).replace(day=1)
            month_end = month_start + relativedelta(months=1)
            count = TravelRequest.search_count(domain + [
                ('request_date', '>=', month_start),
                ('request_date', '<', month_end),
            ])
            months.append({'label': month_start.strftime('%b %Y'), 'count': count})
        max_month_count = max([m['count'] for m in months], default=0)

        approved_with_turnaround = requests_recent.filtered(
            lambda r: r.request_date and r.hr_approved_date
        )
        if approved_with_turnaround:
            total_days = sum(
                (r.hr_approved_date.date() - r.request_date).days
                for r in approved_with_turnaround
            )
            avg_turnaround_days = round(total_days / len(approved_with_turnaround), 1)
        else:
            avg_turnaround_days = 0.0

        return {
            'role': roles['role'],
            'is_admin': roles['is_admin'],
            'is_hr': roles['is_hr'],
            'is_manager': roles['is_manager'],
            'days': days,
            'total_requests': len(requests_recent),
            'state_counts': state_counts,
            'state_labels': state_selection,
            'mybiz_counts': mybiz_counts,
            'mybiz_labels': mybiz_selection,
            'success_rate': success_rate,
            'pushed_count': len(pushed),
            'failed_count': failed_count,
            'pending_manager': pending_manager,
            'pending_hr': pending_hr,
            'mybiz_pending': mybiz_pending,
            'avg_turnaround_days': avg_turnaround_days,
            'upcoming': [{
                'id': u.id,
                'name': u.name,
                'employee': u.employee_id.name,
                'from_city': u.from_city,
                'to_city': u.to_city,
                'departure_date': fields.Date.to_string(u.departure_date),
            } for u in upcoming],
            'recent_failures': [{
                'id': f.id,
                'name': f.name,
                'employee': f.employee_id.name,
                'error': (f.mybiz_error or '')[:140],
            } for f in recent_failures],
            'dept_spend': dept_spend_list,
            'max_dept_amount': max_dept_amount,
            'monthly_trend': months,
            'max_month_count': max_month_count,
            'currency_symbol': self.env.company.currency_id.symbol or '',
        }
