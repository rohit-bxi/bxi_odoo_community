# -*- coding: utf-8 -*-
{
    'name': 'BXI Groups Rules',
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Base Employee group: own-record access only for Employees & Attendance',
    'author': 'BXI',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'hr',
        'hr_attendance',
        'hr_holidays',
    ],
    'data': [
        'security/bxi_groups_rules_security.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
