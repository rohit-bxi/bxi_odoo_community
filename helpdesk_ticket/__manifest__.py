# -*- coding: utf-8 -*-
{
    'name': 'BXI Helpdesk Ticket',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI',
    'summary': 'Employee form customization',
    'description': 'Helpdesk Tickets Customizations',
    'depends': ['helpdesk'],
    'data': [
        'security/ir.model.access.csv',
        'views/helpdesk_ticket_views.xml',
        'views/helpdesk_category_views.xml',
        'views/helpdesk_sub_category_views.xml',
        'views/escalation_level_views.xml'
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
