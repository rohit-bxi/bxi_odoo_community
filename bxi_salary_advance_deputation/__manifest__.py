{
    'name': 'BXI Salary Advance - International Deputation',
    'category': 'Human Resources/Payroll',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'summary': 'Settle salary advances when an employee moves to a host country payroll',
    'description': """
        Links the Salary Advance Policy with the International Deputation Policy.
        - When a deputation is confirmed, advances being recovered move to the Full and Final Settlement, deducted from the last home payslip
        - Balances the home payroll could not recover are listed for recovery by the host payroll
        - HR records the recovery made at the new location
    """,
    'depends': [
        'bxi_salary_advance',
        'bxi_international_deputation',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/host_recovery_wizard_views.xml',
        'views/salary_advance_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': True,
    'license': 'LGPL-3',
}
