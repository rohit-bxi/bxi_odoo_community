# -*- coding: utf-8 -*-
import calendar
import datetime
import json
import logging

import requests
from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TRIP_TYPE_MAP = {
    'one_way': 'ONWARDS',
    'round_trip': 'ROUND_TRIP',
    'multi_city': 'MULTICITY',
}
TRAVEL_CLASS_MAP = {
    'economy': 'ECONOMY',
    'premium_economy': 'PREMIUM_ECONOMY',
    'business': 'BUSINESS',
    'first': 'BUSINESS',  # myBiz has no FIRST class — map to nearest supported tier
}


def _epoch_ms(value):
    """Convert an Odoo Date/Datetime (naive, stored as UTC) to epoch milliseconds."""
    if not value:
        return None
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        value = datetime.datetime.combine(value, datetime.time.min)
    return int(calendar.timegm(value.timetuple()) * 1000)


class TravelRequest(models.Model):
    """
    Replaces bxi_travel_request's myBiz push/payload with one that matches
    the real myBiz Corporate Travel Request API contract:
    POST /corporate/v1/create/partner/travel-request
    { deviceDetails, travellerDetails: {paxDetails}, services: {FLIGHT, HOTEL},
      reasonForTravel: {reason}, approvalDetails: {approvalRequired, approverDetails}, trfId }
    """
    _inherit = 'travel.request'

    mybiz_travel_request_url = fields.Char(
        string='myBiz Travel Request URL',
        readonly=True,
        copy=False,
        help='"travelRequestUrl" returned by myBiz after a successful push.',
    )
    mybiz_response_code = fields.Char(string='myBiz Response Code', readonly=True, copy=False)
    mybiz_response_message = fields.Char(
        string='myBiz Response Message', readonly=True, copy=False)

    # ──────────────────────────────────────────────────────────────
    # Payload construction (real myBiz contract)
    # ──────────────────────────────────────────────────────────────

    def _build_mybiz_pax_details(self):
        self.ensure_one()
        return [{
            'name': self.employee_id.name,
            'email': self.employee_id.work_email or self.email or '',
            'isPrimaryPax': True,
        }]

    def _build_mybiz_flight_service(self, opt):
        """Build one FLIGHT service entry from a travel.request.option, or None."""
        opt._ensure_mybiz_service_id()

        origin_country = opt.origin_country_id or self.from_country
        dest_country = opt.destination_country_id or self.to_country
        departure = opt.departure_datetime
        arrival = opt.arrival_datetime or opt.departure_datetime

        journey = [{
            'from': {
                'airportCode': opt.origin_code or self.from_city,
                'cityName': self.from_city,
                'countryCode': origin_country.code or '',
                'countryName': origin_country.name or '',
            },
            'to': {
                'airportCode': opt.destination_code or self.to_city,
                'cityName': self.to_city,
                'countryCode': dest_country.code or '',
                'countryName': dest_country.name or '',
            },
            'departureDate': _epoch_ms(departure) or _epoch_ms(self.departure_date),
            'arrivalDate': _epoch_ms(arrival) or _epoch_ms(self.departure_date),
        }]

        return {
            'serviceId': opt.mybiz_ref,
            'tripType': TRIP_TYPE_MAP.get(self.trip_type or 'round_trip', 'ONWARDS'),
            'travelClass': TRAVEL_CLASS_MAP.get(
                opt.travel_class or self.travel_class or 'economy', 'ECONOMY'),
            'paxDetails': {
                'adult': 1,
                'child': {'count': 0, 'age': []},
                'infant': 0,
            },
            'journeyDetails': journey,
        }

    def _build_mybiz_hotel_service(self, opt):
        """Build one HOTEL service entry from a travel.request.option, or None."""
        opt._ensure_mybiz_service_id()
        checkin = opt.checkin_date or self.departure_date
        checkout = opt.checkout_date or self.return_date or self.departure_date
        hotel_country = self.to_country

        return {
            'serviceId': opt.mybiz_ref,
            'cityCode': opt.hotel_city or self.hotel_city or self.to_city,
            'cityName': opt.hotel_city or self.hotel_city or self.to_city,
            'countryCode': hotel_country.code or '',
            'countryName': hotel_country.name or '',
            'checkin': _epoch_ms(checkin),
            'checkout': _epoch_ms(checkout),
            'roomDetailsPaxWise': [{
                'adult': 1,
                'child': {'count': 0, 'age': []},
                'infant': 0,
            } for _i in range(max(opt.rooms or 1, 1))],
        }

    def _build_mybiz_payload(self):
        """Build the JSON payload for the myBiz Travel Request API (real contract)."""
        self.ensure_one()
        rec = self

        services = {}

        flight_opts = rec.travel_option_ids.filtered(lambda o: o.option_type == 'flight')
        if not flight_opts and rec.mode_of_travel == 'flight':
            # No structured segment recorded — synthesize one from the header fields
            # so the request is not silently dropped.
            flight_opts = self.env['travel.request.option'].create([{
                'travel_request_id': rec.id,
                'option_type': 'flight',
                'origin_code': rec.from_city,
                'destination_code': rec.to_city,
                'departure_datetime': rec.departure_date,
                'travel_class': rec.travel_class,
                'description': 'Auto-generated from header fields for myBiz push.',
            }])
        if flight_opts:
            services['FLIGHT'] = [rec._build_mybiz_flight_service(opt) for opt in flight_opts]

        hotel_opts = rec.travel_option_ids.filtered(lambda o: o.option_type == 'hotel')
        if not hotel_opts and rec.hotel_required:
            hotel_opts = self.env['travel.request.option'].create([{
                'travel_request_id': rec.id,
                'option_type': 'hotel',
                'hotel_city': rec.hotel_city or rec.to_city,
                'hotel_grade': rec.hotel_grade,
                'checkin_date': rec.hotel_checkin or rec.departure_date,
                'checkout_date': rec.hotel_checkout or rec.return_date,
                'rooms': rec.hotel_rooms or 1,
                'description': 'Auto-generated from header fields for myBiz push.',
            }])
        if hotel_opts:
            services['HOTEL'] = [rec._build_mybiz_hotel_service(opt) for opt in hotel_opts]

        approver_details = []
        if rec.manager_id:
            approver_details.append({
                'approvalLevel': 1,
                'name': rec.manager_id.name,
                'emailId': rec.manager_id.work_email or '',
            })
        if rec.hr_approved_by and rec.hr_approved_by != rec.manager_id:
            approver_details.append({
                'approvalLevel': len(approver_details) + 1,
                'name': rec.hr_approved_by.name,
                'emailId': rec.hr_approved_by.work_email or '',
            })

        return {
            'deviceDetails': {
                'version': '19.0',
                'platform': 'DESKTOP',
            },
            'travellerDetails': {
                'paxDetails': rec._build_mybiz_pax_details(),
            },
            'services': services,
            'reasonForTravel': {
                'reason': rec.travel_purpose,
            },
            'approvalDetails': {
                'approvalRequired': True,
                'approverDetails': approver_details,
            },
            'trfId': rec.name,
        }

    # ──────────────────────────────────────────────────────────────
    # Push / Recall
    # ──────────────────────────────────────────────────────────────

    def _push_to_mybiz(self):
        """Push the approved travel request to myBiz.

        POST /corporate/v1/create/partner/travel-request
        """
        self.ensure_one()
        # sudo: any HR approver must be able to trigger the push even if they
        # don't personally have access to the myBiz Configuration model.
        config = self.env['bxi.mybiz.config'].sudo().get_active_config(self.company_id.id)
        if not config:
            self.write({
                'mybiz_status': 'failed',
                'mybiz_error': (
                    'myBiz configuration not found. Please configure myBiz API settings.'),
            })
            self.message_post(body=_(
                '⚠️ myBiz Push Failed: No active myBiz configuration found for company %s. '
                'Please go to Travel → myBiz Configuration and set up the API credentials.'
            ) % self.company_id.name)
            return

        payload = self._build_mybiz_payload()
        url = config._get_endpoint('travel_request_endpoint')
        headers = config._get_auth_headers()

        _logger.info('Pushing travel request %s to myBiz: %s', self.name, url)
        _logger.debug('myBiz payload: %s', json.dumps(payload, indent=2))

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            resp_data = response.json()

            is_success = str(resp_data.get('status', '')).lower() == 'success'
            self.write({
                'mybiz_travel_request_url': resp_data.get('travelRequestUrl') or False,
                'mybiz_response_code': str(resp_data.get('responseCode') or ''),
                'mybiz_response_message': resp_data.get('message') or '',
                'mybiz_status': 'pending' if is_success else 'failed',
                'mybiz_sync_date': fields.Datetime.now(),
                'mybiz_error': False if is_success else (
                    resp_data.get('message') or 'myBiz returned a non-success status.'),
                'mybiz_raw_response': json.dumps(resp_data, indent=2),
            })
            if is_success:
                self.message_post(
                    body=_('✅ Successfully pushed to MakeMyTrip myBiz.<br/>%s') % (
                        ('<a href="%s" target="_blank">View on myBiz</a>' %
                         resp_data['travelRequestUrl'])
                        if resp_data.get('travelRequestUrl') else ''
                    ),
                    subtype_xmlid='mail.mt_note',
                )
                _logger.info('myBiz push successful for %s', self.name)
            else:
                self.message_post(
                    body=_('❌ myBiz Push Failed: %s') % (resp_data.get('message') or resp_data),
                    subtype_xmlid='mail.mt_note',
                )
                _logger.error('myBiz push rejected for %s: %s', self.name, resp_data)

        except requests.exceptions.HTTPError as e:
            err = f'HTTP {e.response.status_code}: {e.response.text[:500]}'
            self.write({
                'mybiz_status': 'failed',
                'mybiz_error': err,
                'mybiz_sync_date': fields.Datetime.now(),
                'mybiz_raw_response': e.response.text[:2000] if e.response else '',
            })
            self.message_post(
                body=_('❌ myBiz Push Failed: %s') %
                err, subtype_xmlid='mail.mt_note')
            _logger.error('myBiz push HTTP error for %s: %s', self.name, err)

        except requests.exceptions.ConnectionError:
            err = 'Connection error — myBiz API unreachable. Check IP whitelisting.'
            self.write({'mybiz_status': 'failed', 'mybiz_error': err,
                       'mybiz_sync_date': fields.Datetime.now()})
            _logger.error('myBiz connection error for %s', self.name)

        except requests.exceptions.Timeout:
            err = 'Request timed out — myBiz API did not respond within 30 seconds.'
            self.write({'mybiz_status': 'failed', 'mybiz_error': err,
                       'mybiz_sync_date': fields.Datetime.now()})
            _logger.error('myBiz timeout for %s', self.name)

        except Exception as e:
            err = str(e)
            self.write({'mybiz_status': 'failed', 'mybiz_error': err,
                       'mybiz_sync_date': fields.Datetime.now()})
            _logger.error('myBiz unexpected error for %s: %s', self.name, err)

    def action_recall_all_mybiz_services(self):
        """Recall every flight/hotel service already pushed to myBiz for this request."""
        for rec in self:
            pushed_options = rec.travel_option_ids.filtered(
                lambda o: o.mybiz_ref and o.mybiz_status != 'cancelled'
            )
            if not pushed_options:
                raise UserError(_('No myBiz services have been pushed for this request yet.'))
            for opt in pushed_options:
                opt._recall_mybiz_service()
            if all(o.mybiz_status == 'cancelled' for o in rec.travel_option_ids.filtered(
                    lambda o: o.mybiz_ref)):
                rec.write({'mybiz_status': 'cancelled', 'state': 'cancelled'})

    def _sync_mybiz_status(self):
        """
        The published myBiz contract only offers Create and Recall endpoints —
        there is no status-polling endpoint to call. Disable the inherited
        polling behaviour rather than hitting a non-existent/undocumented URL.
        """
        _logger.debug(
            'Skipping myBiz status sync for %s — no status endpoint is defined '
            'in the myBiz Travel Request API contract.', self.name
        )
        return
