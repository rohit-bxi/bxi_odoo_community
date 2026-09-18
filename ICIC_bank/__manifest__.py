# -*- coding: utf-8 -*-
{
    'name': 'ICICI Bank',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'sequence': 1,
    'author': 'BXI Technology',
    'depends': [
        'om_hr_payroll',
        'hr'
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/payslip_view.xml',
        'views/wizard.xml',
    ],
    'external_dependencies': {
        'python': ['Cryptodome', 'requests'],
    },
    'summary': 'Bank Integration ICICI',
    'description': 'Bank Integration ICICI',
    'installable': True,
    'application': False,
    'auto_install': False,
}
