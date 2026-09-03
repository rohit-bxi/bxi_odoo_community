# -*- coding: utf-8 -*-
{
    'name': 'BXI HR Employee',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI',
    'summary': 'Employee form customization',
    'description': 'Employee View Modification',
    'depends': ['hr', 'custom_template', 'contacts','om_hr_payroll'],
    'data': [
        'security/ir.model.access.csv',
        'security/hr_employee_security.xml',
        'views/hr_employee_view.xml',
        'report/payslip_contact_employee.xml',
        'report/relieving_exp_letter.xml',
        'report/data_privacy.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}