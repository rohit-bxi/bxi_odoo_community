{
    'name': 'Biometric Integration',
    'license': 'LGPL-3',
    'author': 'Vijay Shanker Dubey',
    'version': '19.0.1.2.0',
    'category': 'Human Resource',
    'summary': 'Download punches from eSSL/ZKTeco biometric devices into Attendances',
    'depends': ['base', 'mail', 'hr', 'hr_attendance'],
    'external_dependencies': {
        'python': ['pyzk', 'openpyxl'],
    },
    'data': [
            'security/ir.model.access.csv',
            'security/ir_rule.xml',
            'views/hr_employee_view_inherit.xml',
            'views/hr_attendance_view_inherit.xml',
            'views/res_company_view_inherit.xml',
            'views/hr_work_location_view_inherit.xml',
            'views/essl_api_config_view.xml',
            'views/essl_api_sync_log_view.xml',
            'wizard/manual_import_wizard_view.xml',
            'data/attendance_cron.xml',
    ],
    "assets": {
            "web.assets_backend": [
                "odoo_biometric_integration/static/src/js/attendance_menu_extend.js",
            ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
}
