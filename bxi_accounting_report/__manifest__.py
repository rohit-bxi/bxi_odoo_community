{
    'name': 'BXI P&L Report',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI',
    'summary': 'P&L Report',
    'description': 'P&L Report',
    'depends': ['base','accountant','web','base_setup','portal_employee_expense'],
    'data': [
        'security/ir.model.access.csv',
        'views/pl_wizard.xml',
        'views/custom_pl_form.xml',
        'report/pdf_pl.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bxi_accounting_report/static/src/js/pl_dashboard.js',
            'bxi_accounting_report/static/src/xml/pl_dashboard.xml',
        ],  
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}

