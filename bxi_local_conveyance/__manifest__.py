# -*- coding: utf-8 -*-
{
    'name': 'BXI Local Conveyance',
    'category': 'Human Resources',
    'version': '19.0.1.1.0',
    'sequence': 1,
    'author': 'BXI Technologies',
    'website': 'https://bxitech.com/',
    'summary': 'Local Conveyance Policy: travel plans, per-km rates, claim rules and RM/HR approval',
    'description': """
        Implements the BXI Tech Local Conveyance Policy (v1.2).
        - Travel plans by band: TP1 (E6 and above) and TP2 (E3 to E5) by taxi, TP3 (up to E2) by auto or taxi
        - Personal vehicle at the Table A rates: 2-Wheeler 2.50 and 4-Wheeler 5.00 per km, whatever the travel plan
        - Auto-rickshaw at actuals in an emergency (no inter-office cab and no personal transport)
        - Auto-rickshaw claims: Reporting Manager approval, plus HR above Rs. 1,000 for the day; bills required
        - Parking and toll at actuals with receipts, along with a conveyance claim, approved by HR
        - Residence to airport one way at the per-km rates
        - Claims within 45 days, not on weekends or holidays, not beyond two months at another local office
        - Other office assignments start when the work location moves away from the regular office
        - No intercity travel, commute (residence to workplace trips go to HR) or travel between company facilities
        - The same bill cannot be claimed twice; vehicle claims of employees with fuel in the flexi basket go to HR
        - Domestic transfer: drive the own vehicle to the new city at Table A rates or move it, not both, one vehicle
        - Food for the Sales Team: Rs. 1,000 per day with the bill, the excess is borne by the employee
    """,
    'depends': [
        'hr',
        'mail',
        'portal',
        'website',
        'resource',
        'hr_expense',
        'bxi_hr_employee',
        'bxi_certification_reimbursement',
        'portal_employee_expense',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_config_parameter_data.xml',
        'data/travel_plan_data.xml',
        'data/product_data.xml',
        'data/ir_cron_data.xml',
        'wizard/conveyance_refuse_wizard_views.xml',
        'views/hr_expense_views.xml',
        'views/conveyance_travel_plan_views.xml',
        'views/conveyance_office_assignment_views.xml',
        'views/conveyance_transfer_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_department_views.xml',
        'views/res_config_settings_views.xml',
        'views/portal_templates.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'bxi_local_conveyance/static/src/js/portal_conveyance.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
