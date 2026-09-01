# -*- coding: utf-8 -*-
{
    'name': 'BXI HR Company Policy',
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Company Policy Management with In-Screen View-Only Document Viewer',
    'description': """
        Company Policy Management for BXI Odoo.
        - Child menu under Employees: 'Company Policy'
        - 'Policies' Menu: View-only embedded in-screen document preview (no download)
        - 'Upload' Menu: Management list and form view to upload policy documents
    """,
    'author': 'BXI',
    'depends': ['base', 'hr', 'mail', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_company_policy_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bxi_hr_policy/static/src/scss/policy_viewer.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
