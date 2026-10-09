# -*- coding: utf-8 -*-
{
    'name': 'BXI Equitable Benefit - Shift Requests',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'summary': 'Check odd shift work patterns against approved shift requests',
    'description': """
        Equitable Benefit Policy, odd hour / day / week shifts: the working schedule of an employee on each day
        is taken from their approved shift requests, since applying a shift request overwrites the schedule of
        the contract. Payouts of an odd shift work pattern worked mostly outside odd shift schedules are flagged.
    """,
    'depends': ['bxi_equitable_benefit', 'bxi_shift_management'],
    'installable': True,
    'application': False,
    'auto_install': True,
    'license': 'LGPL-3',
}
