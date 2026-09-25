# -*- coding: utf-8 -*-
{
    'name': 'BXI Certification Reimbursement',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI',
    'summary': 'Certification Policy: approved certifications, approvals and reimbursement',
    'description': """
        Implements the BXI Tech Certification Policy.
        - Approved certification catalogue maintained by LoB Academies
        - Inclusion requests for certifications not in the approved list (Annexure B)
        - Reporting Manager pre-approval before the exam (and academy approval for Udemy)
        - Reimbursement claims with the band approval matrix and 90-day escalation
        - Cost charged to the Band 4 head's cost centre
        - Service agreements (Annexure A) signed electronically
        - Automatic refusal on resignation and dues shown in offboarding
        - Company-provided certification vouchers
    """,
    'depends': [
        'hr',
        'mail',
        'portal',
        'analytic',
        'resource',
        'hr_expense',
        'sign',
        'bxi_hr_employee',
        'employee_onboarding',
        'portal_employee_expense',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_config_parameter_data.xml',
        'data/product_data.xml',
        'data/service_agreement_tier_data.xml',
        'data/ir_cron_data.xml',
        'report/service_agreement_report.xml',
        'wizard/bxi_certification_refuse_wizard_views.xml',
        'views/bxi_line_of_business_views.xml',
        'views/bxi_certification_views.xml',
        'views/bxi_certification_request_views.xml',
        'views/bxi_certification_inclusion_views.xml',
        'views/bxi_service_agreement_views.xml',
        'views/bxi_certification_voucher_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_expense_views.xml',
        'views/employee_onboarding_views.xml',
        'views/portal_templates.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
