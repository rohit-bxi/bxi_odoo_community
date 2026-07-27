# -*- coding: utf-8 -*-
{
    'name': 'Travel Request — MakeMyTrip myBiz Integration',
    'category': 'Human Resources',
    'version': '19.0.2.0.0',
    'summary': 'Manage employee travel requests with MakeMyTrip myBiz integration',
    'sequence': 1,
    'author': 'BXI',
    'license': 'LGPL-3',
    'description': '''
        Travel Request module with full MakeMyTrip myBiz corporate integration.
        - Employee submits travel request with flight/hotel/cab/train segments
        - Manager and HR approval workflow
        - On HR approval: automatic push to myBiz Travel Request API
        - Periodic sync of booking status from myBiz
    ''',
    'depends': [
        'base',
        'mail',
        'portal',
        'website',
        'hr',
        'hr_expense',
        'project',
        'account',
        'bxi_user_access',
    ],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'data/sequence.xml',
        'data/mail_template.xml',
        'data/mybiz_cron.xml',
        'views/mybiz_config_views.xml',
        'views/travel_request_views.xml',
        'views/bxi_travel_template.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
