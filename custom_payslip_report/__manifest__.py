# -*- coding: utf-8 -*-
{
    'name': 'BXI Custom Payslip',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI',
    'summary': 'Employee Payslip Customization',
    'description': 'Employee View Modification',
    'depends': ['hr_payroll'],
    'data': [
        'data/ir_cron.xml',
        'report/payslip_report.xml',
        'views/hr_payslip_view.xml',
        'views/payslip_template.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
