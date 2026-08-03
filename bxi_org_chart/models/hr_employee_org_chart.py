# -*- coding: utf-8 -*-
from odoo import models, api, _

class HrEmployeeOrgChart(models.Model):
    _inherit = 'hr.employee'

    @api.model
    def get_org_chart_tree_data(self):
        """
        Builds and returns the complete organization chart hierarchy tree 
        strictly for the currently active company, excluding Administrator user.
        """
        current_company = self.env.company

        # Domain to get active employees of current company only
        domain = [
            ('active', '=', True),
            ('company_id', '=', current_company.id),
        ]

        # Search active employees with sudo()
        employees = self.sudo().search(domain)

        # Filter out 'Administrator' or system admin user employees if any
        filtered_employees = []
        for emp in employees:
            login = (emp.user_id.login or '').lower() if emp.user_id else ''
            emp_name = (emp.name or '').lower()
            if login in ('admin', 'administrator') or 'administrator' in emp_name:
                continue
            filtered_employees.append(emp)

        emp_dict = {}
        valid_emp_ids = {emp.id for emp in filtered_employees}

        for emp in filtered_employees:
            job_name = emp.job_title or (emp.job_id.name if emp.job_id else False) or _("Employee")
            dept_name = emp.department_id.name if emp.department_id else _("General")
            
            # Check if parent is valid and in current active company set
            parent_id = False
            if emp.parent_id and emp.parent_id.id in valid_emp_ids:
                parent_id = emp.parent_id.id

            emp_dict[emp.id] = {
                'id': emp.id,
                'name': emp.name,
                'job_title': job_name,
                'department': dept_name,
                'department_id': emp.department_id.id if emp.department_id else False,
                'work_email': emp.work_email or (emp.user_id.email if emp.user_id else ''),
                'work_phone': emp.work_phone or emp.mobile_phone or '',
                'work_location': emp.work_location_id.name if hasattr(emp, 'work_location_id') and emp.work_location_id else '',
                'avatar_url': f"/web/image?model=hr.employee&id={emp.id}&field=avatar_128",
                'parent_id': parent_id,
                'parent_name': emp.parent_id.name if emp.parent_id else '',
                'children': [],
                'direct_reports_count': 0,
                'total_reports_count': 0,
            }

        # Build parent-child relationships
        root_nodes = []
        for emp_id, data in emp_dict.items():
            parent_id = data['parent_id']
            if parent_id and parent_id in emp_dict:
                emp_dict[parent_id]['children'].append(data)
            else:
                root_nodes.append(data)

        # Recursively calculate report counts
        def calculate_counts(node):
            node['direct_reports_count'] = len(node['children'])
            total = len(node['children'])
            for child in node['children']:
                total += calculate_counts(child)
            node['total_reports_count'] = total
            return total

        for root in root_nodes:
            calculate_counts(root)

        departments_count = len(set(e['department'] for e in emp_dict.values()))

        return {
            'company_name': current_company.name,
            'company_id': current_company.id,
            'board_title': _('Reporting to The Board'),
            'root_nodes': root_nodes,
            'total_employees': len(filtered_employees),
            'total_departments': departments_count,
            'direct_board_reports': len(root_nodes),
        }
