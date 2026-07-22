# -*- coding: utf-8 -*-
{
    'name': 'BXI Shift Management',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI',
    'license': 'LGPL-3',
    'summary': 'Employee Shift/Working Schedule Change Request with 2-Level Approval',
    'description': '''
        Allows employees to request temporary working schedule (shift) changes
        for a specified date range. Features:
        - Manager + HR 2-level approval
        - Automatic schedule application and revert via scheduled actions
        - Role-based record visibility
    ''',
    'depends': [
        'base',
        'mail',
        'hr',
    ],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'data/sequence.xml',
        'data/cron.xml',
        'views/shift_request_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
