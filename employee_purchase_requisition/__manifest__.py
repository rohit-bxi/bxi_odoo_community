# -*- coding: utf-8 -*-
{
    'name': 'Employee Purchase Requisition',
    'version': '19.0.1.0.0',
    'category': 'Purchases',
    'summary': 'Manage material requisition of employees and user',
    'description': """Create the material requisition request and there are 
    multi-level approvals for requests from the department head and requisition 
    manager. Department head has the option to choose vendors for each material. 
    Also we can generate the PDF report for each material requisition""",
    'author': 'Cybrosys Techno Solutions',
    'company': 'Cybrosys Techno Solutions',
    'maintainer': 'Cybrosys Techno Solutions',
    'website': 'https://www.cybrosys.com',
    'depends': ['base', 'hr', 'stock', 'purchase'],
    'data': [
        'security/employee_purchase_requisition_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/mail_template.xml',
        'views/employee_purchase_requisition_views.xml',
        'views/requisition_order_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_department_views.xml',
        'views/purchase_order_views.xml',
        'views/stock_picking_views.xml',
        'views/employee_purchase_requisition_actions.xml',
        'views/employee_purchase_requisition_menu.xml',
        'views/material_requisition_portal_view.xml',
        'report/employee_purchase_requisition_templates.xml',
        'report/employee_purchase_requisition_report.xml',
    ],
    'images': ['static/description/banner.png'],
    'license': 'AGPL-3',
    'installable': True,
    'auto_install': False,
    'application': True,
}

