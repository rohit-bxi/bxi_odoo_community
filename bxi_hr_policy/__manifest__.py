# -*- coding: utf-8 -*-
{
    'name': 'BXI HR Company Policy',
    'version': '19.0.1.1.0',
    'category': 'Human Resources',
    'summary': 'Company Policy Management with In-Screen View-Only Document Viewer',
    'description': """
        Company Policy Management for BXI Odoo.
        - Child menu under Employees: 'Company Policy'
        - 'Policies' Menu: View-only embedded in-screen document preview (no download)
        - 'Upload' Menu: Management list and form view to upload policy documents
        - Policy versions approved by the CPO and published by HR
        - Versioned, evidenced employee acknowledgements (Odoo and portal)
        - Configurable reminders, manager/HR escalation and optional portal lock
    """,
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'depends': ['base', 'hr', 'mail', 'web', 'portal'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'report/policy_acknowledgement_report.xml',
        'views/hr_company_policy_views.xml',
        'views/hr_policy_acknowledgement_views.xml',
        'views/portal_templates.xml',
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
