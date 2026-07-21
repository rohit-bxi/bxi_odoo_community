# -*- coding: utf-8 -*-
{
    "name": "Project Contract Management",
    "version": "1.0",
    "summary": "Manage Contracts with Quarterly Breakdown",
    "category": "Project",
    "author": "Your Company",
    "depends": ['base', 'project', 'mail', 'sale'],
    "data": [
        "security/ir.model.access.csv",
        'views/contract_stage.xml',
        'views/contract_views.xml',
        'views/service_line_views.xml',
        'views/menu.xml',
        'views/account_move_views.xml',
    ],

    'assets': {
        'web.assets_backend': [
            'project_contract_management/static/src/css/contract_kanban.css',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
