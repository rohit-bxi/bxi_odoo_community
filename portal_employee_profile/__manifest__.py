# -*- coding: utf-8 -*-
{
    'name': 'Employee Portal Profile',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI',
    'summary': 'Employee Self Service Portal',
    'description': 'Employee Self Service Portal',
    'depends': [
        'hr',
        'portal',
        'website',
        'l10n_in_hr_payroll',
        'bxi_hr_employee',
    ],
    'data': [
        'views/portal_menu.xml',
        'views/portal_templates.xml',
        # 'views/portal_my_payslips.xml',
    ],
    "assets": {
        "web.assets_frontend": [
            "portal_employee_profile/static/src/css/portal_employee.css",
        ]
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
