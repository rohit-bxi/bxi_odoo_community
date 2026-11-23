# -*- coding: utf-8 -*-
import logging
import uuid

import requests
from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TravelRequestOption(models.Model):
    """
    Adds the fields myBiz actually requires per FLIGHT/HOTEL service
    (origin/destination country, so the API's airportCode/countryCode/
    countryName can be sent correctly) and the ability to recall a single
    service that was already pushed, per the myBiz Recall Travel Request API.
    """
    _inherit = 'travel.request.option'

    origin_country_id = fields.Many2one(
        'res.country',
        string='Origin Country',
        help='Country of the origin airport/city, used for the myBiz journey payload.',
    )
    destination_country_id = fields.Many2one(
        'res.country',
        string='Destination Country',
        help='Country of the destination airport/city, used for the myBiz journey payload.',
    )

    @api.onchange('travel_request_id')
    def _onchange_travel_request_id_mybiz(self):
        for rec in self:
            request = rec.travel_request_id
            if request:
                rec.origin_country_id = rec.origin_country_id or request.from_country
                rec.destination_country_id = rec.destination_country_id or request.to_country

    def _ensure_mybiz_service_id(self):
        """Assign a stable unique serviceId (myBiz's `serviceId`) before first push."""
        for rec in self:
            if not rec.mybiz_ref:
                rec.mybiz_ref = uuid.uuid4().hex
        return True

    def action_recall_service(self):
        """Recall (cancel) this single flight/hotel service already pushed to myBiz."""
        for rec in self:
            rec._recall_mybiz_service()
        return True

    def _recall_mybiz_service(self):
        self.ensure_one()
        if self.mybiz_status == 'cancelled':
            raise UserError(_('This segment is already recalled/cancelled.'))
        # mybiz_ref is assigned while the payload is built, before myBiz
        # answers; only 'confirmed' means myBiz accepted this service.
        if not self.mybiz_ref or self.mybiz_status != 'confirmed':
            raise UserError(
                _('This segment has not been pushed to myBiz yet — nothing to recall.'))

        # sudo: any HR/manager approver must be able to trigger a recall even
        # if they don't personally have access to the myBiz Configuration model.
        config = self.env['bxi.mybiz.config'].sudo().get_active_config(
            self.travel_request_id.company_id.id)
        if not config:
            raise UserError(
                _('myBiz configuration not found. Please configure myBiz API settings.'))

        url = config._get_endpoint('travel_request_recall_endpoint')
        headers = config._get_auth_headers()
        payload = {
            'trfId': self.travel_request_id.name,
            'action': 'recalled',
            'serviceId': self.mybiz_ref,
        }

        _logger.info('Recalling myBiz service %s for travel request %s',
                     self.mybiz_ref, self.travel_request_id.name)

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=20)
            response.raise_for_status()
            resp_data = response.json()
        except requests.exceptions.HTTPError as e:
            resp = e.response
            status = resp.status_code if resp is not None else None
            body = resp.text if resp is not None else ''
            if status == 403 and 'Access Denied' in body:
                raise UserError(_(
                    'MakeMyTrip blocked the recall (HTTP 403 Access Denied) at %s. Check the '
                    'Recall Endpoint in myBiz Configuration: it must be '
                    '/corporate/v1/update/partner/travel-request (not /internal/...). '
                    'If it is, ask the MMT myBiz team to whitelist this server\'s IP.'
                ) % url) from e
            raise UserError(_('myBiz recall failed: HTTP %(status)s %(body)s',
                              status=status, body=body[:300])) from e
        except requests.exceptions.RequestException as e:
            raise UserError(_('myBiz recall request failed: %s') % str(e)) from e

        message = str(resp_data.get('message') or '')
        # Recalled already (e.g. by MMT in the myBiz portal): Odoo just catches up.
        already_recalled = 'cannot change the status of recalled request' in message.lower()
        if str(resp_data.get('status', '')).lower() != 'success' and not already_recalled:
            raise UserError(_('myBiz recall failed: %s') % (message or resp_data))

        self.write({'mybiz_status': 'cancelled'})
        self.travel_request_id._update_mybiz_state_after_recall()
        self.travel_request_id.message_post(
            body=Markup(_('🔁 myBiz service <b>%s</b> (%s) was recalled: %s')) % (
                self.mybiz_ref, self.option_type, resp_data.get(
                    'message') or 'Operation executed successfully.'
            ),
            subtype_xmlid='mail.mt_note',
        )
        _logger.info('myBiz recall successful for service %s', self.mybiz_ref)
