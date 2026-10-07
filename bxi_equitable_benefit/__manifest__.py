# -*- coding: utf-8 -*-
{
    'name': 'BXI Equitable Benefit',
    'category': 'Human Resources',
    'version': '19.0.1.2.0',
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
        - Validation by Revenue Assurance, approval by Finance, payout through payroll with TDS
        - Attendance based unauthorized absence and work pattern compliance checks
        - Full & Final Settlement on resignation or departure, including an unpaid earlier year
        - Performance rating and Annualized Component A taken from released appraisals
    """,
    'depends': [
        'hr',
        'hr_holidays',
        'mail',
        'project',
        'om_hr_payroll',
        'bxi_hr_employee',
        'employee_onboarding',
        'bxi_hr_performance_bonus',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_config_parameter_data.xml',
        'data/work_pattern_data.xml',
        'data/rate_matrix_update.xml',
        'data/salary_rule_data.xml',
        'data/ir_cron_data.xml',
        'report/payout_statement_report.xml',
        'wizard/generate_payout_wizard_views.xml',
        'wizard/component_a_wizard_views.xml',
        'views/work_pattern_views.xml',
        'views/rate_views.xml',
        'views/assignment_views.xml',
        'views/payout_views.xml',
        'views/eligibility_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_version_views.xml',
        'views/hr_leave_type_views.xml',
        'views/hr_employee_appraisal_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'post_init_hook': '_post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
