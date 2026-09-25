# -*- coding: utf-8 -*-
{
    'name': 'BXI International Deputation',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'summary': 'International Deputation - Salary Processing Policy: host payroll start date, gap-day ex-gratia, India payroll proration',
    'description': """
        Implements the BXI Tech International Deputation - Salary Processing Policy.
        - Country salary rules: Calendar Days vs Working Days approach (25 working-day countries seeded)
        - Host working calendars (weekend / public holidays per host country)
        - Deputation record: home payroll last day, host payroll start day, gap days and the one-time ex-gratia (Host Annual Gross / 260 per gap day) on transfer and on return
        - Deputation Commencement Letter sent to the employee on arrival
        - India payslip proration for days on the host payroll (DEP_NOPAY)
        - Deputed employees are skipped by the India office geofence
    """,
    'depends': [
        'hr',
        'mail',
        'resource',
        'om_hr_payroll',
        'custom_payslip_report',
        'bxi_hr_employee',
        'bxi_attendance',
        'bxi_travel_request',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/resource_calendar_data.xml',
        'data/country_rule_data.xml',
        'data/salary_rule_data.xml',
        'data/ir_cron_data.xml',
        'report/deputation_letter_report.xml',
        'data/mail_template_data.xml',
        'views/deputation_views.xml',
        'views/country_rule_views.xml',
        'views/hr_employee_views.xml',
        'views/travel_request_views.xml',
        'views/menus.xml',
    ],
    'post_init_hook': '_post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
