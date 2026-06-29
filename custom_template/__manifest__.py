# -*- coding: utf-8 -*-
{
    'name': 'BXI Custom Template',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI',
    'summary': 'Company specific Template',
    'description': """
        Company specific Template
    """,
    'depends': ['hr'],
    'data': [
        'report/report.xml',
        'report/report_nzero_one.xml',
        'report/report_bxi_foundation.xml',

    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}