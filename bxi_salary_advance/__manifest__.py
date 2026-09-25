{
    'name': 'BXI Salary Advance',
    'category': 'Human Resources/Payroll',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'summary': 'Salary Advance Policy: requests, approvals, disbursement and EMI recovery through payroll',
    'description': """
        Implements the BXI Tech Salary Advance Policy.
        - Category I: salary not processed (India), recovered in full from the next payroll
        - Category II: emergencies, recovered in 3 interest-free EMIs
        - Category III: housing deposit / rent, recovered over the 6/12-month tenancy
        - Eligibility: full-time employees, 6 months of service (waived for Category I joining/transfer delays), not on notice period, no outstanding advance, up to 75% of the monthly salary
        - Category I only when the last payroll did not pay the employee; recovered by the next payroll together with the arrears
        - Policy document linked on the portal; acknowledgement required before applying
        - Reporting Manager approval, HR processing within 7 working days, exception approval and Finance disbursement
        - Loan undertaking for housing advances signed electronically
        - EMIs deducted through the SAL_ADV salary rule; balances moved to the Full and Final Settlement
        - Employee portal to apply, upload the signed request form and follow the recovery
    """,
    'depends': [
        'hr',
        'mail',
        'portal',
        'website',
        'resource',
        'account',
        'sign',
        'om_hr_payroll',
        'custom_payslip_report',
        'bxi_hr_employee',
        'employee_onboarding',
        'bxi_certification_reimbursement',
        'bxi_hr_policy',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_config_parameter_data.xml',
        'data/salary_rule_data.xml',
        'data/ir_cron_data.xml',
        'report/salary_advance_reports.xml',
        'wizard/salary_advance_wizard_views.xml',
        'views/salary_advance_views.xml',
        'views/salary_advance_installment_views.xml',
        'views/hr_employee_views.xml',
        'views/employee_resignation_views.xml',
        'views/bxi_line_of_business_views.xml',
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
