# -*- coding: utf-8 -*-
{
    'name': 'Employee Portal Expenses',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI',
    'summary': 'Employee Expense Submission Portal',
    'description': 'Employee Expense Submission Portal',
    'depends': [
        'hr',
        'portal',
        'website',
        'hr_expense',
        'bxi_user_access'
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/mail_template.xml',
        'views/hr_expense_inherit.xml',
        'views/hr_expense.xml',
        'views/portal_expense_menu.xml',
        'views/portal_expense_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'portal_employee_expense/static/src/js/portal_expense.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
