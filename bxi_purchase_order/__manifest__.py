{
    'name': 'bxi_purchase_order',
    'version': '1.0',
    'summary': 'API for creating purchase order',
    'author': 'Kriti',
    'category': 'Purchase',
    'depends': ['purchase', 'account', 'stock'],
    'data': [
        'views/purchase_order_views.xml',
        'report/purchase_order_report.xml',
        'report/custom_purchase_order_template.xml',
        'report/purchase_order_report_templates.xml',
    ],
    'installable': True,
    'application': False,
}