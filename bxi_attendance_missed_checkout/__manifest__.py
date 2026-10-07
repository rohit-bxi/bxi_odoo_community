# -*- coding: utf-8 -*-
{
    'name': 'BXI Attendance Missed Check-out LWP',
    'category': 'Human Resources',
    'version': '19.0.1.1.0',
    'summary': 'Auto-close forgotten attendances; LWP on WFO/WFH days not regularized by the 25th.',
    'description': '''
        When an employee does not check out on an office (WFO) or home (WFH) day:
        - the open attendance is closed with zero duration,
        - the employee is asked to submit an attendance regularization,
        - the employee can check in normally on the next day.
        A full-day LWP is applied at the monthly cutoff (25th) for days that are
        not regularized; neither the manager nor HR is notified of it.
        Client-site exception days, deputation, weekends and public holidays are exempt.
    ''',
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'license': 'LGPL-3',
    'depends': [
        'hr_attendance',
        'hr_holidays',
        'bxi_attendance',
        'bxi_leave_management',
    ],
    'data': [
        'data/cron_data.xml',
        'data/mail_template.xml',
        'views/hr_attendance_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
