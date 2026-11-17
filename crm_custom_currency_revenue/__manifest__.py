{
    'name': 'CRM Custom Currency & Revenue Multiplier',
    'version': '19.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': 'Manage dynamic currency (INR, AED, USD) beside Expected Revenue and auto-calculate Expected Revenue from Float fields',
    'description': """
CRM Custom Currency & Expected Revenue Multiplier (Odoo 19)
===========================================================
* Allows selecting Currency (INR ₹, AED, USD $, etc.) per Opportunity so the symbol beside Expected Revenue updates dynamically.
* Automatically activates INR, AED, and USD currencies upon installation.
* Adds Float fields (Base Value & Multiplier / Rate) that automatically multiply and update Expected Revenue.
    """,
    'author': 'Custom Odoo Developer',
    'depends': ['crm'],
    'data': [
        'data/res_currency_data.xml',
        'views/crm_lead_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
