# -*- coding: utf-8 -*-
{
    'name': 'BXI Employee Milestones',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'summary': 'Birthday and job anniversary emails; probation confirmation by manager and HR.',
    'description': '''
Daily scheduled jobs:

- "Happy Birthday" email to the employee, copying the reporting manager.
- "Happy Job Anniversary" email to the employee on each completed year of service, copying the reporting manager and HR.
- 10 days before the 6-month probation end date, a probation review starts: the reporting manager confirms, then HR gives the second approval and the employee is confirmed.
    ''',
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'license': 'LGPL-3',
    'depends': ['hr', 'mail', 'bxi_hr_employee'],
    'data': [
        'security/probation_security.xml',
        'security/ir.model.access.csv',
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        'views/hr_probation_review_views.xml',
        'views/hr_employee_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
