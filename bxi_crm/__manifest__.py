# -*- coding: utf-8 -*-
{
    'name': 'BXI CRM',
    'category': 'CRM',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI',
    'license': "LGPL-3",
    'depends': [
        "crm",
        "project_contract_management",
    ],
    'data': [
        "security/ir.model.access.csv",
        "views/presales_poc_views.xml",
        "views/crm_lead_views.xml",
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}