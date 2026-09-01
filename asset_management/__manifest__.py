{
    'name': 'Asset Management — Advanced',
    "version": "2.0",
    'summary': 'Advanced Asset Management with Accounting Integration, KPI Dashboard & Full Depreciation Lifecycle.',
    'description': """
        Advanced Odoo Asset Management Module by BXI Tech.

        Key Features:
        ─────────────
        ✅ Full asset lifecycle: Draft → Confirmed → Disposed
        ✅ Automatic Fixed Asset (account.asset) creation on confirmation
        ✅ Journal entries for: Acquisition, Depreciation, and Disposal
        ✅ 4 Depreciation Methods: Fixed Amount, Percentage, Straight-Line (SLM), Declining Balance
        ✅ KPI Dashboard: 12+ metrics, charts, alert counters
        ✅ Asset Disposal Wizard with proper accounting entries (write-off, sale, transfer)
        ✅ Depreciation Schedule Report (projected + posted)
        ✅ Insurance & warranty tracking with alerts
        ✅ Department, employee custodian, serial number, condition tracking
        ✅ QR code generation, label printing
        ✅ Transfer history, Maintenance cost tracking
        ✅ Chatter/messaging on asset records
    """,
    'category': 'Accounting/Fixed Assets',
    'author': 'BXI Tech',
    'website': '',
    'depends': [
        'base',
        'product',
        'hr',
        'account',
        'purchase',
        'mail',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequence.xml',
        # Wizards
        'wizard/asset_label_wizard_view.xml',
        'wizard/asset_disposal_wizard_view.xml',
        # Reports
        'report/asset_label_report.xml',
        'report/asset_label_templates.xml',
        'report/asset_template_templates.xml',
        'report/depreciation_schedule_report.xml',
        # Views
        'views/asset_views.xml',
        'views/asset_vendor_views.xml',
        'views/asset_dashboard_views.xml',
        'views/asset_report.xml',
        'views/stock_movement_report_views.xml',
        'views/purchase_order_line_view.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'asset_management/static/src/scss/asset_dashboard.scss',
            'asset_management/static/src/js/asset_dashboard.js',
            'asset_management/static/src/xml/asset_dashboard.xml',
        ],
        'web.report_assets_common': [
            'asset_management/static/src/scss/report_label_sheet.scss',
        ],
    },
    'i18n': [
        'i18n/ar.po',
        'i18n/de.po',
        'i18n/es_ES.po',
        'i18n/es.po',
        'i18n/fr.po',
        'i18n/it.po',
        'i18n/nl.po',
        'i18n/pt.po',
        'i18n/tr.po',
    ],
    'images': [
        'static/description/main_screenshot.png',
        'static/description/formate_screenshot_1.png',
        'static/description/formate_screenshot_2.png',
        'static/description/formate_screenshot_3.png',
        'static/description/formate_screenshot_4.png',
        'static/description/formate_screenshot_5.png',
        'static/description/formate_screenshot_6.png',
        'static/description/formate_screenshot_7.png',
    ],
    'application': True,
    'installable': True,
    'price': 0,
    'currency': 'EUR',
    'license': 'LGPL-3',
}
