{
    'name': 'Bxi User Access',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI',
    'summary': 'Manage Vendor and custmer access',
    'description': 'Manage Vendor and custmer access',
    'depends': [
        'hr',
    ],
    'data': [
        'security/user_security.xml',
        'views/res_users.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
