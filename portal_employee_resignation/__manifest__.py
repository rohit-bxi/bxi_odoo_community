# -*- coding: utf-8 -*-
{
    'name': 'Portal Employee Resignation',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI',
    'summary': 'Employee Resignation Portal',
    'description': 'Portal page for employees to apply for resignation',
    'depends': [
        'hr',
        'portal',
        'website',
        'employee_onboarding',
        'bxi_user_access',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/portal_resignation_menu.xml',
        'views/portal_resignation_templates.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
