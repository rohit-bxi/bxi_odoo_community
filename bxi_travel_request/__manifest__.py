# -*- coding: utf-8 -*-
{
    'name': 'Travel Request Management',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'summary': 'Manage employee travel requests in Odoo 19',
    'sequence': 1,
    'author': 'BXI',
    'license': 'LGPL-3',
    'description': 'Employee View Modification',
    'depends': [
        'base',
        'mail',
        'hr',
        'hr_expense',
        'website',
        'project',
        'account',
        'bxi_user_access'
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'data/sequence.xml',
        'data/mail_template.xml',
        'views/travel_request_views.xml',
        'views/menu.xml',
        'views/bxi_travel_template.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'bxi_travel_request/static/src/js/travel.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
