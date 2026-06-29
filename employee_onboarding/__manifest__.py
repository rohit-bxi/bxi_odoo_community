# -*- coding: utf-8 -*-
{
    'name': 'Employee Onboarding',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI',
    'summary': 'Employee Onboarding and Offboarding Management',
    'description': 'Employee Onboarding and Offboarding Management',
    'license': 'LGPL-3',
    'depends': ['base', 'hr', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'security/onboarding_security.xml',
        'views/onboarding_views.xml',
        'views/employee_resignation_views.xml',
        'views/onboarding_menus.xml',
        'views/hr_employee_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
