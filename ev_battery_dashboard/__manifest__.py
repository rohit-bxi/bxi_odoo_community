# -*- coding: utf-8 -*-
{
    'name': 'EV Battery Dashboard',
    'category': 'Fleet',
    'version': '19.0.2.0.0',
    'sequence': 5,
    'author': 'BXI',
    'summary': 'Core Battery KPI Dashboard for EV Fleet Management with .dat Import',
    'description': """
Core Battery KPIs:
1. Battery State of Health (SOH) & Degradation Rate
2. Battery Energy Efficiency (kWh/km)
3. SOC Drop per Trip
4. Charging Behaviour & Battery Cycle Stress
5. Battery Temperature Stress

Additional Features:
- EV Telemetry Device Registry
- .dat File Import Wizard (Fleet + Telemetry)
- Import Batch Tracking & History
- Combined Fleet Overview + EV Battery Dashboard
    """,
    'depends': [
        'fleet',
        'web',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ev_battery_log_data.xml',
        'data/ev_telemetry_data.xml',
        'views/ev_battery_log_views.xml',
        'views/ev_device_views.xml',
        'views/ev_telemetry_log_views.xml',
        'views/ev_import_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ev_battery_dashboard/static/src/js/ev_battery_dashboard.js',
            'ev_battery_dashboard/static/src/xml/ev_battery_dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
