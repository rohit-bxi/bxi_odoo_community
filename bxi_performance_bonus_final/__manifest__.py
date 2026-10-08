{
    "name": "BXI Performance Bonus Policy",
    "version": "19.0.1.1.0",
    "category": "Human Resources",
    "summary": "Performance Bonus Policy integrated with BXI Performance Review",
    "author": "BXI Technology",
    "license": "LGPL-3",
    "depends": [
        "base",
        "hr",
        "mail",
        "bxi_performance_review_owl"
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/bonus_data.xml",
        "views/hr_employee_views.xml",
        "views/performance_bonus_plan_views.xml",
        "views/performance_bonus_cycle_views.xml",
        "views/performance_bonus_line_views.xml",
        "views/performance_bonus_menus.xml"
    ],
    "installable": True,
    "application": True
}
