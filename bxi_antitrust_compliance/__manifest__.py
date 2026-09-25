# -*- coding: utf-8 -*-
{
    'name': 'BXI Antitrust Compliance',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 1,
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'summary': 'Antitrust / Corporate Culture policy: Legal queries, incidents, competitor interactions and bid checks',
    'description': """
        Implements the BXI Tech Antitrust / Corporate Culture policy.
        - "In case of doubt" queries to the compliance mailbox
        - Meeting incident reports (reservation stated, left the meeting, departure recorded)
        - Competitor interaction declarations with CPO review and post-event confirmation
        - Bid / RFP compliance declaration required before a tender bid is sent or won
        - Confidential compliance cases for the CPO
        Policy acknowledgement is handled by bxi_hr_policy.
    """,
    'depends': [
        'hr',
        'mail',
        'portal',
        'crm',
        'sale_crm',
        'bxi_hr_policy',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/antitrust_topic_data.xml',
        'data/ir_config_parameter_data.xml',
        'data/crm_tag_data.xml',
        'data/ir_cron_data.xml',
        'views/antitrust_query_views.xml',
        'views/antitrust_incident_views.xml',
        'views/antitrust_interaction_views.xml',
        'views/antitrust_bid_declaration_views.xml',
        'views/antitrust_case_views.xml',
        'views/antitrust_topic_views.xml',
        'views/antitrust_dashboard_views.xml',
        'views/crm_views.xml',
        'views/hr_employee_views.xml',
        'views/res_config_settings_views.xml',
        'views/portal_templates.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
