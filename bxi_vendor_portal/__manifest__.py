# -*- coding: utf-8 -*-
{
    'name': 'BXI Vendor Management Portal',
    'version': '19.0.1.0.0',
    'category': 'Purchases',
    'summary': 'Complete Vendor Lifecycle Management — Onboarding, Documents, ASN, Portal & Analytics',
    'description': """
BXI Vendor Management System
==============================
Full-feature vendor portal covering:
- Vendor master with auto-generated vendor codes
- GST, PAN, MSME, bank detail capture
- Multi-level maker-checker approval workflow
- Document upload and expiry tracking
- Advance Shipment Notification (ASN) management
- Vendor performance rating and scoring
- OWL-powered analytics dashboards
- Approved Vendor List (AVL) management
    """,
    'author': 'BXI',
    'website': 'https://bxi.in',
    'depends': [
        'base',
        'mail',
        'purchase',
        'account',
        'portal',
        'web',
    ],
    'data': [
        'security/vendor_security_groups.xml',
        'security/ir.model.access.csv',
        'data/vendor_sequence_data.xml',
        'data/vendor_mail_templates.xml',
        'views/vendor_category_views.xml',
        'views/vendor_master_views.xml',
        'views/vendor_document_views.xml',
        'views/vendor_approval_views.xml',
        'views/vendor_asn_views.xml',
        'views/vendor_rating_views.xml',
        'views/vendor_dashboard_views.xml',
        'wizards/vendor_onboard_wizard_views.xml',
        'wizards/vendor_block_wizard_views.xml',
        'views/menus.xml',
        'data/vendor_demo_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bxi_vendor_portal/static/src/js/vendor_dashboard.js',
            'bxi_vendor_portal/static/src/xml/vendor_dashboard.xml',
        ],
    },
    'images': ['static/description/icon.png'],
    'license': 'LGPL-3',
    'installable': True,
    'application': True,
    'auto_install': False,
}
