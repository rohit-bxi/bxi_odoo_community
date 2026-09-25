# -*- coding: utf-8 -*-
{
    'name': 'BXI Equitable Benefit',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'summary': 'Equitable Benefit Policy: work-pattern based annual benefit on Component A',
    'description': """
        Implements the BXI Tech Equitable Benefit Policy.
        - Configurable work patterns and rate matrix (% of Annualized Component A)
        - Employee deployment periods (work category, pattern, onsite/offshore) with approval
        - Eligibility checks: disciplinary action, performance rating, unauthorized absence
        - Pro-rata computation for pattern changes, long unpaid leave and separation (FNF)
        - Validation by Revenue Assurance, approval by Finance, payout through payroll
    """,
    'depends': [
        'hr',
        'hr_holidays',
        'mail',
        'om_hr_payroll',
        'bxi_hr_employee',
        'employee_onboarding',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_config_parameter_data.xml',
        'data/work_pattern_data.xml',
        'data/salary_rule_data.xml',
        'report/payout_statement_report.xml',
        'wizard/generate_payout_wizard_views.xml',
        'views/work_pattern_views.xml',
        'views/rate_views.xml',
        'views/assignment_views.xml',
        'views/payout_views.xml',
        'views/eligibility_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_version_views.xml',
        'views/hr_leave_type_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'post_init_hook': '_post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
