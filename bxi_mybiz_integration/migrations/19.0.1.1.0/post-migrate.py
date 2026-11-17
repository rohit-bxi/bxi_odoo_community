# -*- coding: utf-8 -*-
"""Bring data pushed before 19.0.1.1.0 in line with the new push tracking.

- A segment is only recallable when myBiz accepted it ('confirmed'). Before,
  segments got their serviceId before the POST and stayed 'pending' either way.
- A successful push now moves the request to 'approved' (myBiz has no status
  endpoint, so it never left 'mybiz_pending' before).
Plain SQL on purpose: an ORM write on state would re-send state emails.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE travel_request_option o
           SET mybiz_status = CASE WHEN r.mybiz_status = 'failed' THEN 'failed'
                                   ELSE 'confirmed' END
          FROM travel_request r
         WHERE o.travel_request_id = r.id
           AND o.option_type IN ('flight', 'hotel')
           AND o.mybiz_ref IS NOT NULL
           AND o.mybiz_status = 'pending'
           AND r.mybiz_status IN ('pending', 'approved', 'booked', 'failed')
    """)
    _logger.info('bxi_mybiz_integration: %s pushed segment(s) re-flagged', cr.rowcount)
    cr.execute("""
        UPDATE travel_request
           SET state = 'approved'
         WHERE state = 'mybiz_pending'
           AND mybiz_status IN ('pending', 'approved', 'booked')
    """)
    _logger.info('bxi_mybiz_integration: %s pushed request(s) moved to approved',
                 cr.rowcount)
