{
    'name': 'Time Off Code for Leave Type',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI',
    'summary': 'Add Time Off Code field in Leave Type',
    'description': 'Add Time Off Code field in Leave Type',
    'depends': ['hr_holidays'],
    'data': [
        'data/leave_cron.xml',
        'views/hr_employee_view.xml',
        'views/hr_leave_type_view.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
