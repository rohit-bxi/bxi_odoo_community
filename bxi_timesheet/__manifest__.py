# -*- coding: utf-8 -*-
{
    'name': 'BXI DeskTime Timesheet Integration',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI',
    'license': 'LGPL-3',
    'summary': 'Sync employee attendance data from DeskTime API into Odoo Timesheets',
    'description': '''
        Daily scheduled sync from DeskTime API:
        - Fetches all employee data for the current day
        - Matches DeskTime employees to Odoo employees by email
        - Creates or updates timesheet (account.analytic.line) records
        - Stores a detailed DeskTime log for audit and reporting
    ''',
    'depends': [
        'base',
        'mail',
        'hr',
        'hr_timesheet',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'data/cron.xml',
        'views/timesheet_dashboard_views.xml',
        'views/timesheet_line_views.xml',
        'views/desktime_config_views.xml',
        'views/desktime_log_views.xml',
        'views/monthly_attendance_timesheet_wizard_views.xml',
        'views/menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bxi_timesheet/static/src/css/timesheet_dashboard.css',
            'bxi_timesheet/static/src/js/timesheet_dashboard.js',
            'bxi_timesheet/static/src/xml/timesheet_dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
