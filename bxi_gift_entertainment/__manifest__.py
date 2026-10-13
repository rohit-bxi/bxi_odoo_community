# -*- coding: utf-8 -*-
{
    'name': 'BXI Gift and Entertainment',
    'category': 'Human Resources',
    'version': '19.0.2.0.0',
    'sequence': 1,
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'summary': 'Gift and Entertainment Policy: gifts given and received, donations, sponsorships, '
               'due diligence, Ethics Committee and expense controls',
    'description': """
        Implements the BXI Gift and Entertainment Policy.
        - Approval matrix by value and region (India in INR, other countries in USD), kept as data
        - Gift Request / Entertainment Information with the prohibited items and Government Official rules
        - Receipt of Gift declarations with the return-to-donor flow and covering letter
        - Donations, charitable and business sponsorships, solicitation of sponsorship
        - LSO due diligence questionnaire and Ethics Committee quorum approvals
        - Extortion payment reports and policy violation cases (anonymous reporting, blacklisting)
        - Expense claims: approved request, entertainment details, certification, alcohol approval,
          45-day donation claims and Mexico fiscal folio
        Approvers come from the L1-L4 Heads of the employee master and the MD / CEO / CFO / Board groups.
    """,
    'depends': [
        'hr',
        'mail',
        'hr_expense',
        'bxi_hr_employee',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_config_parameter_data.xml',
        'data/gift_zone_data.xml',
        'data/gift_item_type_data.xml',
        'data/gift_threshold_data.xml',
        'data/due_diligence_question_data.xml',
        'data/product_data.xml',
        'data/ir_cron_data.xml',
        'report/return_letter_report.xml',
        'wizard/reason_wizard_views.xml',
        'views/approval_line_views.xml',
        'views/gift_request_views.xml',
        'views/gift_receipt_views.xml',
        'views/donation_views.xml',
        'views/sponsorship_views.xml',
        'views/due_diligence_views.xml',
        'views/extortion_views.xml',
        'views/violation_views.xml',
        'views/configuration_views.xml',
        'views/res_partner_views.xml',
        'views/hr_expense_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'post_init_hook': '_post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
