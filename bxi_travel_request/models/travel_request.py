# -*- coding: utf-8 -*-
import json
import logging
import requests
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TravelRequest(models.Model):
    _name = 'travel.request'
    _description = 'Travel Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    # ─── Identity ─────────────────────────────────────────────────
    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default='New',
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        string='Currency',
        readonly=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        tracking=True,
        default=lambda self: self._default_employee_id(),
    )
    manager_id = fields.Many2one('hr.employee', string='Reporting Manager', tracking=True)
    department_id = fields.Many2one('hr.department', string='Department', tracking=True)
    request_by = fields.Many2one(
        'hr.employee',
        string='Requested By',
        default=lambda self: self._default_employee_id(),
        readonly=True,
        tracking=True,
    )
    request_date = fields.Date(
        string='Request Date',
        default=fields.Date.context_today,
        tracking=True,
    )

    # ─── Purpose ──────────────────────────────────────────────────
    travel_purpose = fields.Char(string='Purpose of Travel', required=True, tracking=True)
    project_id = fields.Many2one('project.project', string='Project', tracking=True)
    analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='Analytic Account',
        tracking=True,
    )
    other_info = fields.Text(string='Additional Notes', tracking=True)

    # ─── From ─────────────────────────────────────────────────────
    from_city = fields.Char(string='From City', required=True, tracking=True)
    from_state = fields.Many2one(
        'res.country.state',
        string='From State',
        domain="[('country_id', '=', from_country)]",
        tracking=True,
    )
    from_country = fields.Many2one(
        'res.country',
        string='From Country',
        required=True,
        default=lambda self: self.env.ref('base.in').id,
        tracking=True,
    )
    from_address = fields.Char(string='From Address', tracking=True)

    # ─── To ───────────────────────────────────────────────────────
    to_city = fields.Char(string='To City', required=True, tracking=True)
    to_state = fields.Many2one(
        'res.country.state',
        string='To State',
        domain="[('country_id', '=', to_country)]",
        tracking=True,
    )
    to_country = fields.Many2one(
        'res.country',
        string='To Country',
        required=True,
        default=lambda self: self.env.ref('base.in').id,
        tracking=True,
    )
    to_address = fields.Char(string='To Address', tracking=True)

    # ─── Dates ────────────────────────────────────────────────────
    departure_date = fields.Date(string='Departure Date', required=True, tracking=True)
    return_date = fields.Date(string='Return Date', tracking=True)
    days = fields.Float(
        string='Duration (Days)',
        compute='_compute_days',
        store=True,
        tracking=True,
    )

    # ─── Travel Mode & Preferences ────────────────────────────────
    mode_of_travel = fields.Selection([
        ('flight', 'Flight'),
        ('train', 'Train'),
        ('bus', 'Bus'),
        ('cab', 'Cab / Car'),
        ('ship', 'Ship'),
        ('other', 'Other'),
    ], string='Primary Mode of Travel', tracking=True)

    trip_type = fields.Selection([
        ('one_way', 'One Way'),
        ('round_trip', 'Round Trip'),
        ('multi_city', 'Multi City'),
    ], string='Trip Type', default='round_trip', tracking=True)

    travel_class = fields.Selection([
        ('economy', 'Economy'),
        ('premium_economy', 'Premium Economy'),
        ('business', 'Business'),
        ('first', 'First Class'),
    ], string='Preferred Travel Class', default='economy', tracking=True)

    # ─── Hotel Requirement ────────────────────────────────────────
    hotel_required = fields.Boolean(string='Hotel Required', tracking=True)
    hotel_city = fields.Char(string='Hotel City')
    hotel_grade = fields.Selection([
        ('budget', 'Budget'),
        ('3', '3 Star'),
        ('4', '4 Star'),
        ('5', '5 Star'),
    ], string='Hotel Grade', default='3')
    hotel_checkin = fields.Date(string='Hotel Check-in')
    hotel_checkout = fields.Date(string='Hotel Check-out')
    hotel_rooms = fields.Integer(string='Rooms', default=1)

    # ─── Cab Requirement ─────────────────────────────────────────
    cab_required = fields.Boolean(string='Cab Required', tracking=True)
    cab_type = fields.Selection([
        ('sedan', 'Sedan'),
        ('suv', 'SUV'),
        ('hatchback', 'Hatchback'),
        ('tempo', 'Tempo Traveller'),
        ('any', 'Any'),
    ], string='Cab Type', default='any')
    cab_pickup = fields.Char(string='Cab Pickup Location')
    cab_dropoff = fields.Char(string='Cab Drop Location')

    # ─── Travel Options (selected preferences per segment) ────────
    travel_option_ids = fields.One2many(
        'travel.request.option',
        'travel_request_id',
        string='Travel Segments / Options',
        copy=True,
    )

    # ─── Contact ──────────────────────────────────────────────────
    contact_number = fields.Char(string='Contact Number', tracking=True)
    email = fields.Char(string='Email', tracking=True)

    # ─── Advance Payment ─────────────────────────────────────────
    advance_required = fields.Boolean(string='Advance Required', tracking=True)
    advance_amount = fields.Monetary(
        string='Advance Amount',
        currency_field='currency_id',
        tracking=True,
    )
    advance_notes = fields.Text(string='Advance Notes', tracking=True)

    # ─── Expense Lines ────────────────────────────────────────────
    expense_line_ids = fields.One2many(
        'travel.request.expense.line',
        'travel_request_id',
        string='Post-Travel Expense Lines',
        copy=True,
    )
    expense_line_count = fields.Integer(
        string='Expense Line Count',
        compute='_compute_expense_line_count',
    )
    total_submitted_expense = fields.Monetary(
        string='Total Expense Amount',
        compute='_compute_total_expense_amount',
        store=True,
        currency_field='currency_id',
    )

    # ─── Approval ────────────────────────────────────────────────
    manager_approved_by = fields.Many2one('hr.employee', string='Manager Approved By', readonly=True, tracking=True)
    manager_approved_date = fields.Datetime(string='Manager Approved On', readonly=True, tracking=True)
    hr_approved_by = fields.Many2one('hr.employee', string='HR Approved By', readonly=True, tracking=True)
    hr_approved_date = fields.Datetime(string='HR Approved On', readonly=True, tracking=True)

    # ─── myBiz Integration ───────────────────────────────────────
    mybiz_service_id = fields.Char(
        string='myBiz Service ID',
        readonly=True,
        copy=False,
        tracking=True,
        help='Unique service reference ID returned by myBiz after successful push.',
    )
    mybiz_booking_ref = fields.Char(
        string='myBiz Booking Reference',
        readonly=True,
        copy=False,
        tracking=True,
    )
    mybiz_status = fields.Selection([
        ('not_pushed', 'Not Pushed'),
        ('pending', 'Pending at myBiz'),
        ('approved', 'Booking Approved'),
        ('booked', 'Booked'),
        ('cancelled', 'Cancelled'),
        ('failed', 'Push Failed'),
    ], string='myBiz Status', default='not_pushed', readonly=True, tracking=True)
    mybiz_sync_date = fields.Datetime(string='Last myBiz Sync', readonly=True)
    mybiz_error = fields.Text(string='myBiz Last Error', readonly=True)
    mybiz_raw_response = fields.Text(string='myBiz Raw Response', readonly=True)

    # ─── Status ──────────────────────────────────────────────────
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('manager_approval', 'Manager Approval'),
        ('hr_approval', 'HR Approval'),
        ('mybiz_pending', 'myBiz Pending'),
        ('approved', 'Approved & Booked'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    # ─── Computed Flags ──────────────────────────────────────────
    can_manager_approve = fields.Boolean(
        compute='_compute_can_manager_approve',
        string='Can Manager Approve',
    )
    can_hr_approve = fields.Boolean(
        compute='_compute_can_hr_approve',
        string='Can HR Approve',
    )
    mybiz_status_badge = fields.Char(
        compute='_compute_mybiz_status_badge',
        string='myBiz Badge',
    )
    option_count = fields.Integer(
        compute='_compute_option_count',
        string='Travel Segments',
    )

    # ──────────────────────────────────────────────────────────────
    # Defaults & Computed
    # ──────────────────────────────────────────────────────────────

    @api.model
    def _default_employee_id(self):
        employee = self.env['hr.employee'].search(
            [('user_id', '=', self.env.user.id)], limit=1
        )
        return employee.id if employee else False

    @api.depends('departure_date', 'return_date')
    def _compute_days(self):
        for rec in self:
            rec.days = 0
            if rec.departure_date and rec.return_date:
                if rec.return_date >= rec.departure_date:
                    delta = rec.return_date - rec.departure_date
                    rec.days = delta.days + 1

    @api.depends('expense_line_ids.amount')
    def _compute_total_expense_amount(self):
        for rec in self:
            rec.total_submitted_expense = sum(rec.expense_line_ids.mapped('amount'))

    @api.depends('expense_line_ids')
    def _compute_expense_line_count(self):
        for rec in self:
            rec.expense_line_count = len(rec.expense_line_ids)

    @api.depends('travel_option_ids')
    def _compute_option_count(self):
        for rec in self:
            rec.option_count = len(rec.travel_option_ids)

    def action_view_options(self):
        """Open the travel options/segments list for this request."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Travel Segments — %s') % self.name,
            'res_model': 'travel.request.option',
            'view_mode': 'list,form',
            'domain': [('travel_request_id', '=', self.id)],
            'context': {'default_travel_request_id': self.id},
        }

    @api.depends('employee_id')
    def _compute_can_manager_approve(self):
        current_employee = self.env['hr.employee'].search(
            [('user_id', '=', self.env.user.id)], limit=1
        )
        for rec in self:
            rec.can_manager_approve = bool(
                rec.employee_id
                and rec.employee_id.parent_id
                and current_employee
                and rec.employee_id.parent_id.id == current_employee.id
            )

    def _compute_can_hr_approve(self):
        is_hr = self.env.user.has_group('hr.group_hr_user') or \
                self.env.user.has_group('hr.group_hr_manager') or \
                self.env.user.has_group('base.group_system')
        for rec in self:
            rec.can_hr_approve = is_hr

    @api.depends('mybiz_status')
    def _compute_mybiz_status_badge(self):
        labels = {
            'not_pushed': '⬜ Not Pushed',
            'pending': '🟡 Pending at myBiz',
            'approved': '🟢 myBiz Approved',
            'booked': '✅ Booked',
            'cancelled': '🔴 Cancelled',
            'failed': '❌ Push Failed',
        }
        for rec in self:
            rec.mybiz_status_badge = labels.get(rec.mybiz_status or 'not_pushed', '—')

    # ──────────────────────────────────────────────────────────────
    # Onchange
    # ──────────────────────────────────────────────────────────────

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        for rec in self:
            if rec.employee_id:
                rec.manager_id = rec.employee_id.parent_id.id or False
                rec.department_id = rec.employee_id.department_id.id or False
                rec.contact_number = rec.employee_id.work_phone or rec.employee_id.mobile_phone or False
                rec.email = rec.employee_id.work_email or False

    @api.onchange('hotel_required')
    def _onchange_hotel_required(self):
        if self.hotel_required and not self.hotel_city:
            self.hotel_city = self.to_city
        if self.hotel_required and not self.hotel_checkin:
            self.hotel_checkin = self.departure_date
        if self.hotel_required and not self.hotel_checkout:
            self.hotel_checkout = self.return_date

    @api.onchange('cab_required')
    def _onchange_cab_required(self):
        if self.cab_required and not self.cab_pickup:
            self.cab_pickup = self.to_city

    # ──────────────────────────────────────────────────────────────
    # Constraints
    # ──────────────────────────────────────────────────────────────

    @api.constrains('departure_date', 'return_date')
    def _check_dates(self):
        for rec in self:
            if rec.departure_date and rec.return_date and rec.return_date < rec.departure_date:
                raise UserError(_('Return date cannot be earlier than departure date.'))

    @api.constrains('hotel_checkin', 'hotel_checkout')
    def _check_hotel_dates(self):
        for rec in self:
            if rec.hotel_required and rec.hotel_checkin and rec.hotel_checkout:
                if rec.hotel_checkout <= rec.hotel_checkin:
                    raise UserError(_('Hotel checkout date must be after check-in date.'))

    # ──────────────────────────────────────────────────────────────
    # CRUD
    # ──────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('travel.request') or 'BXI/TR/0001'
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if 'state' in vals:
            for record in self:
                record._send_state_email()
        return res

    # ──────────────────────────────────────────────────────────────
    # Workflow Actions
    # ──────────────────────────────────────────────────────────────

    def action_submit(self):
        """Employee submits the travel request — goes to manager for approval."""
        for rec in self:
            if not rec.travel_option_ids:
                raise UserError(_(
                    'Please add at least one travel segment (flight / hotel / cab / train) '
                    'in the "Travel Segments" tab before submitting.'
                ))
            rec.write({'state': 'manager_approval'})
            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=rec.manager_id.user_id.id if rec.manager_id and rec.manager_id.user_id else False,
                summary=_('Travel Request Pending Your Approval'),
                note=_('Travel request %s from %s is awaiting your approval.') % (rec.name, rec.employee_id.name),
            )

    def manager_action_approve(self):
        """Manager approves — moves to HR approval."""
        for rec in self:
            if not rec.can_manager_approve:
                raise UserError(_('You are not authorized to approve this travel request.'))
            rec.write({
                'state': 'hr_approval',
                'manager_approved_by': self.env.user.employee_id.id,
                'manager_approved_date': fields.Datetime.now(),
            })

    def manager_action_refuse(self):
        """Manager refuses — moves back to draft."""
        for rec in self:
            rec.write({'state': 'cancelled'})
            rec.message_post(body=_('Travel request refused by manager %s.') % self.env.user.name)

    def hr_action_approve(self):
        """HR approves — pushes to myBiz."""
        for rec in self:
            if not rec.can_hr_approve:
                raise UserError(_('You are not authorized to perform HR approval.'))
            rec.write({
                'state': 'mybiz_pending',
                'hr_approved_by': self.env.user.employee_id.id,
                'hr_approved_date': fields.Datetime.now(),
            })
            # Push to myBiz after HR approval
            rec._push_to_mybiz()

    def hr_action_refuse(self):
        """HR refuses — cancels the request."""
        for rec in self:
            rec.write({'state': 'cancelled'})
            rec.message_post(body=_('Travel request refused by HR %s.') % self.env.user.name)

    def action_cancel(self):
        """Cancel the travel request."""
        for rec in self:
            if rec.state == 'approved':
                raise UserError(_('Approved and booked requests cannot be directly cancelled. Please contact HR.'))
            rec.write({'state': 'cancelled'})

    def action_reset_to_draft(self):
        """Reset to draft — admin only."""
        if not self.env.user.has_group('base.group_system'):
            raise UserError(_('Only System Administrators can reset a travel request to draft.'))
        self.write({
            'state': 'draft',
            'manager_approved_by': False,
            'manager_approved_date': False,
            'hr_approved_by': False,
            'hr_approved_date': False,
            'mybiz_service_id': False,
            'mybiz_booking_ref': False,
            'mybiz_status': 'not_pushed',
            'mybiz_error': False,
        })

    # ──────────────────────────────────────────────────────────────
    # myBiz API Integration
    # ──────────────────────────────────────────────────────────────

    def _build_mybiz_payload(self):
        """Build the JSON payload for the myBiz Travel Request API."""
        self.ensure_one()
        rec = self

        # ── Traveller Details ─────────────────────────────────────
        traveller_details = [{
            'name': rec.employee_id.name,
            'email': rec.employee_id.work_email or rec.email or '',
            'mobile': rec.contact_number or '',
            'isPrimary': True,
        }]

        # ── Flight Segments ───────────────────────────────────────
        flight_segments = []
        for opt in rec.travel_option_ids.filtered(lambda o: o.option_type == 'flight'):
            seg = {
                'origin': opt.origin_code or rec.from_city,
                'destination': opt.destination_code or rec.to_city,
                'travelDate': opt.departure_datetime.strftime('%Y-%m-%d') if opt.departure_datetime else str(rec.departure_date),
            }
            if opt.departure_datetime:
                seg['departureTime'] = opt.departure_datetime.strftime('%H:%M')
            if opt.operator:
                seg['preferredAirline'] = opt.operator
            flight_segments.append(seg)

        # Default flight segment from main request if no flight options defined
        if not flight_segments and rec.mode_of_travel == 'flight':
            flight_segments = [{
                'origin': rec.from_city,
                'destination': rec.to_city,
                'travelDate': str(rec.departure_date),
            }]

        # ── Flight Details ────────────────────────────────────────
        class_map = {
            'economy': 'ECONOMY',
            'premium_economy': 'PREMIUM_ECONOMY',
            'business': 'BUSINESS',
            'first': 'FIRST',
        }
        trip_type_map = {
            'one_way': 'ONWARDS',
            'round_trip': 'ROUND_TRIP',
            'multi_city': 'MULTICITY',
        }
        flight_details = None
        if flight_segments or rec.mode_of_travel == 'flight':
            flight_details = {
                'tripType': trip_type_map.get(rec.trip_type or 'round_trip', 'ONWARDS'),
                'travelClass': class_map.get(rec.travel_class or 'economy', 'ECONOMY'),
                'segments': flight_segments,
                'adultCount': 1,
            }

        # ── Hotel Details ─────────────────────────────────────────
        hotel_details = None
        hotel_opts = rec.travel_option_ids.filtered(lambda o: o.option_type == 'hotel')
        if hotel_opts:
            h = hotel_opts[0]
            hotel_details = {
                'cityCode': h.hotel_city or rec.to_city,
                'checkIn': str(h.checkin_date or rec.departure_date),
                'checkOut': str(h.checkout_date or (rec.return_date or rec.departure_date)),
                'rooms': h.rooms or 1,
                'occupancy': 1,
            }
            if h.hotel_grade:
                hotel_details['starRating'] = h.hotel_grade if h.hotel_grade != 'budget' else '2'
        elif rec.hotel_required:
            hotel_details = {
                'cityCode': rec.hotel_city or rec.to_city,
                'checkIn': str(rec.hotel_checkin or rec.departure_date),
                'checkOut': str(rec.hotel_checkout or (rec.return_date or rec.departure_date)),
                'rooms': rec.hotel_rooms or 1,
                'occupancy': 1,
            }
            if rec.hotel_grade:
                hotel_details['starRating'] = rec.hotel_grade if rec.hotel_grade != 'budget' else '2'

        # ── Cab Details ───────────────────────────────────────────
        cab_details = None
        cab_opts = rec.travel_option_ids.filtered(lambda o: o.option_type == 'cab')
        if cab_opts:
            c = cab_opts[0]
            cab_details = {
                'pickupLocation': c.pickup_location or rec.to_city,
                'dropLocation': c.drop_location or '',
                'pickupDateTime': c.pickup_datetime.strftime('%Y-%m-%d %H:%M') if c.pickup_datetime else str(rec.departure_date),
                'cabType': (c.cab_type or 'any').upper(),
            }
        elif rec.cab_required:
            cab_details = {
                'pickupLocation': rec.cab_pickup or rec.to_city,
                'dropLocation': rec.cab_dropoff or '',
                'pickupDateTime': str(rec.departure_date),
                'cabType': (rec.cab_type or 'any').upper(),
            }

        # ── Approver Details ─────────────────────────────────────
        approver = {}
        if rec.hr_approved_by:
            approver = {
                'name': rec.hr_approved_by.name,
                'email': rec.hr_approved_by.work_email or '',
            }
        elif rec.manager_id:
            approver = {
                'name': rec.manager_id.name,
                'email': rec.manager_id.work_email or '',
            }

        # ── Full Payload ──────────────────────────────────────────
        payload = {
            'travellerDetails': traveller_details,
            'reasonForTravel': rec.travel_purpose,
            'approverDetails': approver,
            'internalReference': rec.name,
            'deviceDetails': {
                'platform': 'ODOO',
                'version': '19',
            },
        }
        if flight_details:
            payload['flightDetails'] = flight_details
        if hotel_details:
            payload['hotelDetails'] = hotel_details
        if cab_details:
            payload['cabDetails'] = cab_details

        return payload

    def _push_to_mybiz(self):
        """Push the approved travel request to the myBiz API."""
        self.ensure_one()
        config = self.env['bxi.mybiz.config'].get_active_config(self.company_id.id)
        if not config:
            self.write({
                'mybiz_status': 'failed',
                'mybiz_error': 'myBiz configuration not found. Please configure myBiz API settings.',
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

            service_id = (
                resp_data.get('serviceId') or
                resp_data.get('travelRequestId') or
                resp_data.get('id') or
                ''
            )
            booking_ref = resp_data.get('bookingRef') or resp_data.get('referenceId') or ''

            self.write({
                'mybiz_service_id': str(service_id) if service_id else False,
                'mybiz_booking_ref': str(booking_ref) if booking_ref else False,
                'mybiz_status': 'pending',
                'mybiz_sync_date': fields.Datetime.now(),
                'mybiz_error': False,
                'mybiz_raw_response': json.dumps(resp_data, indent=2),
            })
            self.message_post(
                body=_('✅ Successfully pushed to MakeMyTrip myBiz. Service ID: <b>%s</b>') % (service_id or '—'),
                subtype_xmlid='mail.mt_note',
            )
            _logger.info('myBiz push successful for %s — Service ID: %s', self.name, service_id)

        except requests.exceptions.HTTPError as e:
            err = f'HTTP {e.response.status_code}: {e.response.text[:500]}'
            self.write({
                'mybiz_status': 'failed',
                'mybiz_error': err,
                'mybiz_sync_date': fields.Datetime.now(),
                'mybiz_raw_response': e.response.text[:2000] if e.response else '',
            })
            self.message_post(
                body=_('❌ myBiz Push Failed: %s') % err,
                subtype_xmlid='mail.mt_note',
            )
            _logger.error('myBiz push HTTP error for %s: %s', self.name, err)

        except requests.exceptions.ConnectionError:
            err = 'Connection error — myBiz API unreachable. Check IP whitelisting.'
            self.write({'mybiz_status': 'failed', 'mybiz_error': err, 'mybiz_sync_date': fields.Datetime.now()})
            _logger.error('myBiz connection error for %s', self.name)

        except requests.exceptions.Timeout:
            err = 'Request timed out — myBiz API did not respond within 30 seconds.'
            self.write({'mybiz_status': 'failed', 'mybiz_error': err, 'mybiz_sync_date': fields.Datetime.now()})
            _logger.error('myBiz timeout for %s', self.name)

        except Exception as e:
            err = str(e)
            self.write({'mybiz_status': 'failed', 'mybiz_error': err, 'mybiz_sync_date': fields.Datetime.now()})
            _logger.error('myBiz unexpected error for %s: %s', self.name, err)

    def action_retry_mybiz_push(self):
        """Manually retry the myBiz push for failed/pending requests."""
        for rec in self:
            if rec.state not in ('mybiz_pending', 'cancelled'):
                raise UserError(_('Only requests in "myBiz Pending" or "Cancelled" state can be retried.'))
            if rec.state == 'cancelled' and rec.mybiz_status == 'failed':
                rec.write({'state': 'mybiz_pending', 'mybiz_status': 'not_pushed'})
            rec._push_to_mybiz()

    def action_sync_mybiz_status(self):
        """Poll myBiz for the latest booking status."""
        for rec in self:
            rec._sync_mybiz_status()

    def _sync_mybiz_status(self):
        """Fetch and update booking status from myBiz."""
        self.ensure_one()
        if not self.mybiz_service_id:
            return
        config = self.env['bxi.mybiz.config'].get_active_config(self.company_id.id)
        if not config:
            return

        url = config._get_endpoint('fetch_status_endpoint')
        headers = config._get_auth_headers()
        params = {'serviceId': self.mybiz_service_id}

        try:
            response = requests.get(url, headers=headers, params=params, timeout=15)
            response.raise_for_status()
            resp_data = response.json()

            raw_status = (
                resp_data.get('status') or
                resp_data.get('bookingStatus') or
                resp_data.get('approvalStatus') or
                ''
            ).lower()

            status_map = {
                'approved': 'approved',
                'booked': 'booked',
                'confirmed': 'booked',
                'cancelled': 'cancelled',
                'pending': 'pending',
                'failed': 'failed',
            }
            new_mybiz_status = status_map.get(raw_status, self.mybiz_status)

            new_booking_ref = (
                resp_data.get('bookingRef') or
                resp_data.get('pnr') or
                self.mybiz_booking_ref or
                ''
            )

            write_vals = {
                'mybiz_status': new_mybiz_status,
                'mybiz_sync_date': fields.Datetime.now(),
                'mybiz_raw_response': json.dumps(resp_data, indent=2),
            }
            if new_booking_ref:
                write_vals['mybiz_booking_ref'] = new_booking_ref

            # Promote Odoo state if booking confirmed
            if new_mybiz_status == 'booked' and self.state == 'mybiz_pending':
                write_vals['state'] = 'approved'
            elif new_mybiz_status == 'cancelled' and self.state == 'mybiz_pending':
                write_vals['state'] = 'cancelled'

            self.write(write_vals)
            _logger.info('myBiz status sync for %s: %s', self.name, new_mybiz_status)

        except Exception as e:
            _logger.warning('myBiz status sync failed for %s: %s', self.name, str(e))

    @api.model
    def _cron_sync_mybiz_status(self):
        """Scheduled action: poll myBiz status for all pending requests."""
        pending = self.search([
            ('state', '=', 'mybiz_pending'),
            ('mybiz_service_id', '!=', False),
        ])
        for rec in pending:
            try:
                rec._sync_mybiz_status()
            except Exception as e:
                _logger.error('cron myBiz sync failed for %s: %s', rec.name, str(e))
        _logger.info('myBiz cron sync complete — processed %d records', len(pending))

    # ──────────────────────────────────────────────────────────────
    # Email Notifications
    # ──────────────────────────────────────────────────────────────

    def _send_state_email(self):
        self.ensure_one()
        template = False
        email_to = False
        if self.state == 'manager_approval':
            template = self.env.ref('bxi_travel_request.email_template_manager', raise_if_not_found=False)
            email_to = self.employee_id.parent_id.work_email if self.employee_id.parent_id else False
        elif self.state == 'hr_approval':
            template = self.env.ref('bxi_travel_request.email_template_hr', raise_if_not_found=False)
            email_to = 'hr@bxitech.com'
        elif self.state == 'approved':
            template = self.env.ref('bxi_travel_request.email_template_approved', raise_if_not_found=False)
            email_to = self.employee_id.work_email or self.email
        if not template or not email_to:
            return
        try:
            template.send_mail(
                self.id,
                email_values={'email_to': email_to},
                force_send=True,
            )
        except Exception as e:
            _logger.warning('Failed to send email for travel request %s: %s', self.name, str(e))