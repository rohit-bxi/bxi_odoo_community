# -*- coding: utf-8 -*-
{
    'name': 'BXI Specialized Training - Travel Requests',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'summary': 'Count approved travel requests in the consolidated cost of a specialized training',
    'description': """
        Links travel requests to specialized trainings. The travel booked through an approved travel request
        is part of the consolidated cost of the training (Training Policy, clause 1) and therefore of the
        amount repayable under its service agreement.
    """,
    'depends': ['bxi_training_policy', 'bxi_travel_request'],
    'data': [
        'views/travel_request_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': True,
    'license': 'LGPL-3',
}
