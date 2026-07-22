# -*- coding: utf-8 -*-
{
    'name': 'BXI Financial Report',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Reporting',
    'summary': 'Add custom BXI financial and Fbook reports',
    'description': """
        This module adds a custom sub-menu "BXI Reports" under Accounting -> Reporting,
        with a menu item "Fbook Report" which opens a parameters wizard and displays the comparative report.
    """,
    'author': 'BXI',
    'depends': ['base', 'account', 'sale', 'project_contract_management'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_partner_views.xml',
        'views/fbook_report_wizard_views.xml',
        'views/fbook_report_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bxi_financial_report/static/src/js/fbook_dashboard.js',
            'bxi_financial_report/static/src/xml/fbook_dashboard.xml',
        ],  
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
