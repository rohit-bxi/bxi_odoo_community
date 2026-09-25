# -*- coding: utf-8 -*-
{
    'name': 'HDFC Bank - Payroll Bulk Payment',
    'category': 'Human Resources/Payroll',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'summary': 'Company-specific bulk salary payouts through HDFC Bank with OTP approval and accounting',
    'description': """
HDFC Bank Payroll Bulk Payment
==============================
* Per-company HDFC configuration (credentials, debit account, accounting)
* Payout batches built from confirmed payslips, honouring the employee salary distribution
* OTP-approved bulk submission, scheduled status reconciliation and reversal
* Journal entries on bank confirmation (Salary Payable or Salary Expense, configurable)
* Masked API audit log
""",
    'depends': [
        'om_hr_payroll',
        'hr',
        'account',
        'mail',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence.xml',
        'data/ir_cron.xml',
        'views/hdfc_bank_config_views.xml',
        'views/hdfc_payout_batch_views.xml',
        'views/hdfc_payout_line_views.xml',
        'views/hdfc_api_log_views.xml',
        'views/hr_payslip_views.xml',
        'views/hr_payslip_run_views.xml',
        'views/wizard_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
