# -*- coding: utf-8 -*-
{
    'name': 'BXI Attendance Extension',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'summary': 'Automated shift-based late check-in time off management and auto check-out tracking for employee attendance.',
    'author': 'BXI',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'hr',
        'hr_attendance',
        'bxi_hr_employee',
    ],
    'data': [
        'data/cron_data.xml',
        'views/hr_attendance_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
