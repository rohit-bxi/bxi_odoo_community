# -*- coding: utf-8 -*-
{
    'name': 'BXI HR Employee Promotion/Bonus Letter',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI',
    'summary': 'Employee Appraisal, Promotion & Bonus Management',
    'description': """
        Employee Appraisal & Promotion Management

        Features:
        - Employee Appraisal Records
        - Promotion & Bonus Letters
        - Smart Button on Employee Form
        - Salary Structure Calculation
        - Performance/Bonus Tracking
        - PDF Reports
    """,
    'depends': ['hr', 'mail','custom_template'],
    'data': [
        'security/ir.model.access.csv',
        'views/employee_letter_wizard.xml',
        'views/hr_employee_view.xml',
        'views/hr_apprsail_promotion.xml',
        'report/employee_paperformate.xml',
        'report/report_employee_bonus_letter.xml',
        'report/report_apprsail_promotion.xml',
        'report/report_promotion_letter.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
