# -*- coding: utf-8 -*-
{
    'name': 'BXI API Controller',
    'version': '1.0.0',
    'category': 'Technical',
    'summary': 'REST JSON API endpoints for BXI HRMS data',
    'description': """
        Provides REST API endpoints to expose HR employee data as JSON.
        Endpoint: GET /api/v1/employees
        Returns all active and archived employees with all standard + custom fields.
    """,
    'author': 'BXI Tech',
    'website': 'https://bxitech.com',
    'depends': ['hr', 'base'],
    'data': [],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
