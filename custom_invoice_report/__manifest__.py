# -*- coding: utf-8 -*-
{
    'name': 'BXI Custom Invoice',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI',
    'summary': 'Invoice Report Customization',
    'description': 'Invoice Report Customization',
    'depends': ['account'],
    'data': [
        'report/account_invoice_report.xml',
        'views/custom_invoice_template.xml',
        'views/account_invoice_view.xml',
        'views/res_user.xml',
    ],
    'assets': {
                'web.report_assets_common': [
                'custom_invoice_report/static/src/css/invoice.css',
                ],
            },
    'installable': True,
    'application': False,
    'auto_install': False,
}
