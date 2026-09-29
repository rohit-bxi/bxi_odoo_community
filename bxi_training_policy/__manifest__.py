# -*- coding: utf-8 -*-
{
    'name': 'BXI Specialized Training',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'summary': 'Training Policy: nominations, training agreements, service agreements, advances, claims and recovery',
    'description': """
        Implements the BXI Tech Training Policy (specialized training, domestic and international).
        - Nomination by the Department Head, notified to HR at least 20 days before the training
        - Training Agreement Form signed by the employee at least 7 days before the training
        - Service agreement when the consolidated cost reaches the threshold (1 or 2 years by cost), executed on stamp paper, witnessed and notarised, verified by HR
        - Training cost paid upfront as an advance, settled off once the service period is served
        - Post-training claim under "Specialized Training" with the Initiator -> RM -> HR -> ES approval
        - Full repayment (no pro-rata) when the employee leaves before the end of the service period, recovered in the Full and Final Settlement through payroll, then followed up legally
        - One service agreement per training program
    """,
    'depends': [
        'hr',
        'mail',
        'portal',
        'website',
        'account',
        'hr_expense',
        'sign',
        'om_hr_payroll',
        'bxi_hr_employee',
        'employee_onboarding',
        'portal_employee_expense',
        'bxi_hr_policy',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_config_parameter_data.xml',
        'data/product_data.xml',
        'data/agreement_tier_data.xml',
        'data/salary_rule_data.xml',
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        'report/training_reports.xml',
        'wizard/training_wizard_views.xml',
        'views/training_request_views.xml',
        'views/training_agreement_views.xml',
        'views/training_agreement_tier_views.xml',
        'views/training_recovery_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_expense_views.xml',
        'views/employee_resignation_views.xml',
        'views/employee_onboarding_views.xml',
        'views/res_config_settings_views.xml',
        'views/portal_templates.xml',
        'views/menus.xml',
    ],
    'post_init_hook': '_post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
