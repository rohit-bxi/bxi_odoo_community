{
    "name": "BXI Comp-Off Requests",
    "version": "19.0.1.0.0",
    "summary": "Separate Comp-Off request workflow for weekend work",
    "category": "Human Resources/Time Off",
    "license": "LGPL-3",
    "depends": ["hr", "hr_attendance", "hr_holidays", "mail"],
    "data": [
        "security/comp_off_security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/comp_off_request_views.xml",
    ],
    "application": True,
    "installable": True,
}
