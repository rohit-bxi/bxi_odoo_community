# -*- coding: utf-8 -*-
{
    'name': 'MakeMyTrip myBiz Integration',
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'sequence': 5,
    'author': 'BXI',
    'license': 'LGPL-3',
    'summary': 'Spec-compliant MakeMyTrip myBiz Travel Request API integration with dashboard',
    'description': '''
        Corrects and completes the MakeMyTrip myBiz Corporate Travel Request API
        integration on top of the Travel Request module:
        - Rebuilds the push payload to match the official myBiz contract
          (deviceDetails / travellerDetails.paxDetails / services.FLIGHT|HOTEL /
          reasonForTravel / approvalDetails / trfId), including epoch-millisecond
          dates and per-segment serviceId generation.
        - Authenticates using the real myBiz headers: partner-apikey, client-code.
        - Adds the Recall Travel Request API so an HR/Admin user can recall a
          single pushed flight/hotel service (POST .../update/partner/travel-request).
        - Adds a myBiz Integration Dashboard: request funnel, push success/failure
          rate, pending approvals, upcoming approved travel, department spend and
          a 6-month trend.
    ''',
    'depends': [
        'bxi_travel_request',
    ],
    'data': [
        'data/mybiz_cron_data.xml',
        'views/mybiz_config_views.xml',
        'views/travel_request_views.xml',
        'views/mybiz_dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bxi_mybiz_integration/static/src/css/mybiz_dashboard.css',
            'bxi_mybiz_integration/static/src/js/mybiz_dashboard.js',
            'bxi_mybiz_integration/static/src/xml/mybiz_dashboard.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
