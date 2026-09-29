# -*- coding: utf-8 -*-
{
    'name': 'BXI Local Conveyance - Specialized Training',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'summary': 'No local conveyance claims for travel related to training programs',
    'description': """
        Local Conveyance Policy, exceptions: reimbursements for local travel related to training programs are
        not permitted. Conveyance claims dated during a specialized training of the employee are refused; the
        travel of a training is part of its own claim under the Training Policy.
    """,
    'depends': ['bxi_local_conveyance', 'bxi_training_policy'],
    'installable': True,
    'application': False,
    'auto_install': True,
    'license': 'LGPL-3',
}
