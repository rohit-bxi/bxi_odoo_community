# -*- coding: utf-8 -*-
"""myBiz confirmed the Recall API lives at /corporate/v1/update/partner/travel-request.

The /internal/ path used before is not open to partners and always returned
Akamai 403 "Access Denied".
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE bxi_mybiz_config
           SET travel_request_recall_endpoint = replace(
                   travel_request_recall_endpoint,
                   '/internal/corporate/v1/update/partner/travel-request',
                   '/corporate/v1/update/partner/travel-request')
         WHERE travel_request_recall_endpoint LIKE '%/internal/corporate/v1/update/partner/travel-request%'
    """)
    _logger.info('bxi_mybiz_integration: %s recall endpoint(s) moved off /internal/', cr.rowcount)
