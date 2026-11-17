# -*- coding: utf-8 -*-
{
    'name': 'GLPI Asset Sync',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Fixed Assets',
    'summary': 'Two-way synchronisation between GLPI 11 (High-Level API v2) and Asset Management',
    'description': """
        Connects Asset Management to GLPI 11 through the OAuth2 High-Level REST API.

        GLPI -> Odoo (pull)
        ───────────────────
        ✅ Imports Computers / Printers / Monitors / Peripherals / Phones / Network devices
        ✅ Links existing assets by serial number, inventory number or hostname
        ✅ Creates new Draft assets for unknown GLPI items
        ✅ Keeps hardware facts (serial, model, CPU / RAM / disk, last inventory) up to date
        ✅ Skips templates, items without serial number and junk names
        ✅ Flags custodian mismatches, trashed and purged GLPI items for review

        Odoo -> GLPI (push)
        ───────────────────
        ✅ Custodian, operational status, location and Odoo asset reference
        ✅ Financial information (value, purchase / in-service dates, warranty, supplier)
        ✅ Optional creation in GLPI of assets that only exist in Odoo

        Field ownership is fixed per field so the two systems never overwrite each other.
    """,
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'depends': [
        'asset_management',
        'hr',
        'mail',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        'security/glpi_security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'wizard/glpi_sync_wizard_views.xml',
        'views/glpi_config_views.xml',
        'views/glpi_mapping_views.xml',
        'views/glpi_sync_log_views.xml',
        'views/asset_management_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
