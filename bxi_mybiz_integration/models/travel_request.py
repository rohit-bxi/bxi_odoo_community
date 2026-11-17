# -*- coding: utf-8 -*-
import calendar
import datetime
import json
import logging

import requests
from markupsafe import Markup
from odoo import fields, models, _
from odoo.exceptions import UserError

from .mmt_codes import resolve_airport_code, resolve_city_code

_logger = logging.getLogger(__name__)

TRIP_TYPE_ONWARDS = 'ONWARDS'
TRIP_TYPE_ROUND_TRIP = 'ROUND_TRIP'
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

    def _build_mybiz_pax_details(self, problems=None):
        self.ensure_one()
        email = self.employee_id.work_email or self.email or ''
        if not email and problems is not None:
            problems.append(_(
                'Traveller %s has no email address (set the employee\'s Work Email).'
            ) % (self.employee_id.name or ''))
        return [{
            'name': self.employee_id.name,
            'email': email,
            'isPrimaryPax': True,
        }]

    def _mybiz_airport(self, value, country, problems, label):
        code = resolve_airport_code(value, country.name)
        if not code and problems is not None:
            problems.append(_(
                '%(label)s: no airport found for "%(value)s". Enter the 3-letter IATA '
                'code (e.g. DEL, BOM) in the travel segment.',
                label=label, value=value or '',
            ))
        return code or value or ''

    def _mybiz_journey(self, origin, origin_country, origin_city, dest, dest_country,
                       dest_city, departure, arrival, problems, label):
        return {
            'from': {
                'airportCode': self._mybiz_airport(
                    origin, origin_country, problems, _('%s origin') % label),
                'cityName': origin_city,
                'countryCode': origin_country.code or '',
                'countryName': origin_country.name or '',
            },
            'to': {
                'airportCode': self._mybiz_airport(
                    dest, dest_country, problems, _('%s destination') % label),
                'cityName': dest_city,
                'countryCode': dest_country.code or '',
                'countryName': dest_country.name or '',
            },
            'departureDate': _epoch_ms(departure),
            'arrivalDate': _epoch_ms(arrival or departure),
        }

    def _build_mybiz_flight_service(self, opt, problems=None, with_return=False):
        """Build one FLIGHT service entry from a travel.request.option.

        Each segment is its own service (so it can be recalled on its own) and
        is sent as ONWARDS. The one exception: a round-trip request with a
        single flight segment also gets the return leg, as ROUND_TRIP.
        """
        opt._ensure_mybiz_service_id()
        label = _('Flight %s→%s') % (opt.origin_code or self.from_city,
                                      opt.destination_code or self.to_city)

        origin_country = opt.origin_country_id or self.from_country
        dest_country = opt.destination_country_id or self.to_country
        departure = opt.departure_datetime or self.departure_date
        journeys = [self._mybiz_journey(
            opt.origin_code or self.from_city, origin_country, self.from_city,
            opt.destination_code or self.to_city, dest_country, self.to_city,
            departure, opt.arrival_datetime, problems, label,
        )]
        if with_return:
            journeys.append(self._mybiz_journey(
                opt.destination_code or self.to_city, dest_country, self.to_city,
                opt.origin_code or self.from_city, origin_country, self.from_city,
                self.return_date, None, problems, _('%s return') % label,
            ))

        return {
            'serviceId': opt.mybiz_ref,
            'tripType': TRIP_TYPE_ROUND_TRIP if with_return else TRIP_TYPE_ONWARDS,
            'travelClass': TRAVEL_CLASS_MAP.get(
                opt.travel_class or self.travel_class or 'economy', 'ECONOMY'),
            'paxDetails': {
                'adult': 1,
                'child': {'count': 0, 'age': []},
                'infant': 0,
            },
            'journeyDetails': journeys,
        }

    def _build_mybiz_hotel_service(self, opt, problems=None):
        """Build one HOTEL service entry from a travel.request.option."""
        opt._ensure_mybiz_service_id()
        checkin = opt.checkin_date or self.departure_date
        checkout = opt.checkout_date or self.return_date or self.departure_date
        hotel_country = self.to_country
        city = opt.hotel_city or self.hotel_city or self.to_city
        resolved = resolve_city_code(city, hotel_country.name)
        if not resolved and problems is not None:
            problems.append(_(
                'Hotel: no MakeMyTrip city found for "%s". Check the hotel city spelling.'
            ) % (city or ''))
        city_code, city_name = resolved or (city, city)

        return {
            'serviceId': opt.mybiz_ref,
            'cityCode': city_code,
            'cityName': city_name,
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

    def _has_mybiz_services(self):
        """True when the request has something myBiz can book (a flight or a
        hotel). Mirrors _prepare_mybiz_options without creating anything."""
        self.ensure_one()
        return bool(
            self.travel_option_ids.filtered(lambda o: o.option_type in ('flight', 'hotel'))
            or self.mode_of_travel == 'flight'
            or self.hotel_required
        )

    def _prepare_mybiz_options(self):
        """Create the flight/hotel segment from the header fields when the
        request asks for one but has no structured segment, so it is not
        silently dropped."""
        self.ensure_one()
        Option = self.env['travel.request.option']
        options = self.travel_option_ids
        if self.mode_of_travel == 'flight' and not options.filtered(
                lambda o: o.option_type == 'flight'):
            Option.create({
                'travel_request_id': self.id,
                'option_type': 'flight',
                'origin_code': self.from_city,
                'destination_code': self.to_city,
                'departure_datetime': self.departure_date,
                'travel_class': self.travel_class,
                'description': 'Auto-generated from header fields for myBiz push.',
            })
        if self.hotel_required and not options.filtered(lambda o: o.option_type == 'hotel'):
            Option.create({
                'travel_request_id': self.id,
                'option_type': 'hotel',
                'hotel_city': self.hotel_city or self.to_city,
                'hotel_grade': self.hotel_grade,
                'checkin_date': self.hotel_checkin or self.departure_date,
                'checkout_date': self.hotel_checkout or self.return_date,
                'rooms': self.hotel_rooms or 1,
                'description': 'Auto-generated from header fields for myBiz push.',
            })

    def _get_mybiz_service_options(self):
        self.ensure_one()
        return self.travel_option_ids.filtered(lambda o: o.option_type in ('flight', 'hotel'))

    def _build_mybiz_payload(self, problems=None):
        """Build the JSON payload for the myBiz Travel Request API (real contract).

        When ``problems`` is a list, anything myBiz would reject (unknown
        airport/city, missing email, ...) is appended to it as a message.
        """
        self.ensure_one()
        rec = self

        services = {}
        flight_opts = rec.travel_option_ids.filtered(lambda o: o.option_type == 'flight')
        if flight_opts:
            with_return = (len(flight_opts) == 1 and rec.trip_type == 'round_trip'
                           and bool(rec.return_date))
            services['FLIGHT'] = [
                rec._build_mybiz_flight_service(opt, problems, with_return=with_return)
                for opt in flight_opts]

        hotel_opts = rec.travel_option_ids.filtered(lambda o: o.option_type == 'hotel')
        if hotel_opts:
            services['HOTEL'] = [rec._build_mybiz_hotel_service(opt, problems)
                                 for opt in hotel_opts]

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
                'paxDetails': rec._build_mybiz_pax_details(problems),
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

    def _record_mybiz_push_failure(self, err, raw_response=None):
        """Mark the push as failed on the request and its segments, and say so
        in the chatter so HR sees it without opening the myBiz tab."""
        self.ensure_one()
        vals = {
            'mybiz_status': 'failed',
            'mybiz_error': err,
            'mybiz_sync_date': fields.Datetime.now(),
        }
        if raw_response is not None:
            vals['mybiz_raw_response'] = raw_response
        self.write(vals)
        self._get_mybiz_service_options().filtered(
            lambda o: o.mybiz_status not in ('confirmed', 'cancelled')
        ).write({'mybiz_status': 'failed'})
        self.message_post(
            body=_('❌ myBiz Push Failed: %s') % err,
            subtype_xmlid='mail.mt_note',
        )

    def _push_to_mybiz(self):
        """Push the approved travel request to myBiz.

        POST /corporate/v1/create/partner/travel-request
        """
        self.ensure_one()
        if not self._has_mybiz_services():
            # myBiz only books flights and hotels and rejects a request with no
            # services, so bus/train/cab-only trips are approved and booked offline.
            self.write({
                'state': 'approved',
                'mybiz_status': 'not_pushed',
                'mybiz_error': False,
            })
            self.message_post(
                body=_('ℹ️ Not sent to MakeMyTrip myBiz: myBiz only books flights and hotels, '
                       'and this request has neither. The request is approved — please '
                       'arrange this travel outside myBiz.'),
                subtype_xmlid='mail.mt_note',
            )
            _logger.info('myBiz push skipped for %s: no flight or hotel to book', self.name)
            return

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

        self._prepare_mybiz_options()
        problems = []
        payload = self._build_mybiz_payload(problems=problems)
        if problems:
            self._record_mybiz_push_failure(
                _('Not sent — fix these and click Retry: %s') % '; '.join(problems))
            _logger.warning('myBiz push blocked for %s: %s', self.name, problems)
            return

        url = config._get_endpoint('travel_request_endpoint')
        headers = config._get_auth_headers()

        _logger.info('Pushing travel request %s to myBiz: %s', self.name, url)
        _logger.debug('myBiz payload: %s', json.dumps(payload, indent=2))

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            resp_data = response.json()
        except requests.exceptions.HTTPError as e:
            # A Response is falsy for 4xx/5xx, so compare against None.
            body = e.response.text if e.response is not None else ''
            code = e.response.status_code if e.response is not None else '?'
            err = f'HTTP {code}: {body[:500]}'
            self._record_mybiz_push_failure(err, raw_response=body[:2000])
            _logger.error('myBiz push HTTP error for %s: %s', self.name, err)
            return
        except requests.exceptions.Timeout:
            err = ('Request timed out — myBiz did not respond within 30 seconds. '
                   'Check on myBiz whether the request was created before retrying.')
            self._record_mybiz_push_failure(err)
            _logger.error('myBiz timeout for %s', self.name)
            return
        except requests.exceptions.ConnectionError:
            err = 'Connection error — myBiz API unreachable. Check IP whitelisting.'
            self._record_mybiz_push_failure(err)
            _logger.error('myBiz connection error for %s', self.name)
            return
        except Exception as e:
            err = str(e)
            self._record_mybiz_push_failure(err)
            _logger.error('myBiz unexpected error for %s: %s', self.name, err)
            return

        is_success = str(resp_data.get('status', '')).lower() == 'success'
        self.write({
            'mybiz_travel_request_url': resp_data.get('travelRequestUrl') or False,
            'mybiz_response_code': str(resp_data.get('responseCode') or ''),
            'mybiz_response_message': resp_data.get('message') or '',
            'mybiz_sync_date': fields.Datetime.now(),
            'mybiz_raw_response': json.dumps(resp_data, indent=2),
        })
        if not is_success:
            self._record_mybiz_push_failure(
                resp_data.get('message') or 'myBiz returned a non-success status.')
            _logger.error('myBiz push rejected for %s: %s', self.name, resp_data)
            return

        self._get_mybiz_service_options().write({'mybiz_status': 'confirmed'})
        # myBiz publishes no status endpoint, so Odoo's part ends here: the
        # request is approved and the traveller books it on myBiz.
        self.write({
            'mybiz_status': 'pending',
            'mybiz_error': False,
            'state': 'approved',
        })
        body = _('✅ Successfully pushed to MakeMyTrip myBiz.')
        if resp_data.get('travelRequestUrl'):
            body = Markup('%s<br/><a href="%s" target="_blank">%s</a>') % (
                body, resp_data['travelRequestUrl'], _('View on myBiz'))
        self.message_post(body=body, subtype_xmlid='mail.mt_note')
        _logger.info('myBiz push successful for %s', self.name)

    def _update_mybiz_state_after_recall(self):
        """Cancel the request once every service sent to myBiz is recalled."""
        for rec in self:
            sent = rec._get_mybiz_service_options().filtered(
                lambda o: o.mybiz_status in ('confirmed', 'cancelled'))
            if sent and all(o.mybiz_status == 'cancelled' for o in sent):
                rec.write({'mybiz_status': 'cancelled', 'state': 'cancelled'})

    def action_recall_all_mybiz_services(self):
        """Recall every flight/hotel service sent to myBiz for this request.

        Each recall is a separate call to myBiz. A failure on one service must
        not roll back the services myBiz has already recalled, so errors are
        collected and reported instead of raised.
        """
        failures = []
        for rec in self:
            sent = rec._get_mybiz_service_options().filtered(
                lambda o: o.mybiz_status == 'confirmed')
            if not sent:
                raise UserError(_('No myBiz services have been pushed for this request yet.'))
            rec_failures = []
            for opt in sent:
                try:
                    opt._recall_mybiz_service()
                except Exception as e:  # noqa: BLE001 — keep the recalls that succeeded
                    msg = e.args[0] if isinstance(e, UserError) else str(e)
                    rec_failures.append(f'{opt.option_type} {opt.mybiz_ref}: {msg}')
            if rec_failures:
                rec.message_post(
                    body=_('⚠️ Some myBiz services could not be recalled: %s')
                    % '; '.join(rec_failures),
                    subtype_xmlid='mail.mt_note',
                )
                failures += [f'{rec.name} / {f}' for f in rec_failures]
        if failures:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('myBiz Recall'),
                    'message': '\n'.join(failures),
                    'type': 'warning',
                    'sticky': True,
                    'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                },
            }
        return True

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
