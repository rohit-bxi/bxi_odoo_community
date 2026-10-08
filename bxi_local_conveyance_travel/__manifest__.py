# -*- coding: utf-8 -*-
{
    'name': 'BXI Local Conveyance - Travel Requests',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'summary': 'No local conveyance claims while on an intercity travel request',
    'description': """
        Local Conveyance Policy, clause 4: intercity travel expenses are processed through HR and Finance. Local
        conveyance claims dated during a travel request of the employee are refused: the expenses of the trip,
        local conveyance at the destination included, are claimed with the travel request. Residence to airport
        and back on the departure and return days remains a local conveyance claim (clause 7).
    """,
    'depends': ['bxi_local_conveyance', 'bxi_travel_request'],
    'installable': True,
    'application': False,
    'auto_install': True,
    'license': 'LGPL-3',
}
