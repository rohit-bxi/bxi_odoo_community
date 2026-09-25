{
    'name': 'bxi_purchase_order',
    'version': '1.0',
    'summary': 'API for creating purchase order',
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'category': 'Purchase',
    'depends': ['purchase', 'account', 'stock', 'bxi_crm'],
    'data': [
        'views/purchase_order_views.xml',
        'report/purchase_order_report.xml',
        'report/custom_purchase_order_template.xml',
        'report/purchase_order_report_templates.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}