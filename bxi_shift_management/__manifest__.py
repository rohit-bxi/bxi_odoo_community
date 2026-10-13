# -*- coding: utf-8 -*-
{
    'name': 'BXI Shift Management',
    'category': 'Human Resources',
    'version': '19.0.1.2.0',
    'sequence': 1,
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'license': 'LGPL-3',
    'summary': 'Employee Shift/Working Schedule Change Request with 2-Level Approval',
    'description': '''
        Allows employees to request temporary working schedule (shift) changes
        for a specified date range. Features:
        - Manager + HR 2-level approval
        - Automatic schedule application and revert via scheduled actions
        - Role-based record visibility
        - Attendance regularization (also Missing Timesheet / Late Checkout)
        - Missing timesheet check (Missing Timesheet request)
        - Weekly summary to managers and HR until the 25th, LWP at the cutoff
        - Approved regularized hours counted in the shift wise production hours
    ''',
    'depends': [
        'base',
        'mail',
        'hr',
        'bxi_attendance',
        'bxi_attendance_missed_checkout',
        'bxi_timesheet',
    ],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'data/sequence.xml',
        'data/cron.xml',
        'data/mail_template.xml',
        'views/shift_request_views.xml',
        'views/shift_exception_views.xml',
        'views/menu.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
