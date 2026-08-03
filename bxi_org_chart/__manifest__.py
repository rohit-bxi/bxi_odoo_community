# -*- coding: utf-8 -*-
{
    'name': 'BXI Organization Chart',
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Interactive drill-down organization chart for Odoo HR',
    'description': """
        BXI Organization Chart:
        - Displays the active company's complete organization chart starting from "Reporting to The Board".
        - Interactive drill-down nodes with direct report counters.
        - Click to expand/collapse subordinate branches.
        - Instant employee search, zoom controls, and quick employee profile access.
    """,
    'author': 'BXI',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'web',
        'hr',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/org_chart_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bxi_org_chart/static/src/css/org_chart.css',
            'bxi_org_chart/static/src/js/org_chart_action.js',
            'bxi_org_chart/static/src/xml/org_chart_action.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
