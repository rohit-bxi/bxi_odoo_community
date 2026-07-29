# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class TravelRequestOption(models.Model):
    """
    Stores structured travel preferences/options selected by the employee
    for a travel request. These are pushed to myBiz after HR approval.
    """
    _name = 'travel.request.option'
    _description = 'Travel Request — myBiz Option / Preference'
    _order = 'option_type, sequence, id'

    travel_request_id = fields.Many2one(
        'travel.request',
        string='Travel Request',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(string='Sequence', default=10)

    option_type = fields.Selection([
        ('flight', '✈ Flight'),
        ('hotel', '🏨 Hotel'),
        ('cab', '🚗 Cab / Car'),
        ('train', '🚆 Train'),
        ('bus', '🚌 Bus'),
    ], string='Type', required=True)

    # ─── Common Fields ─────────────────────────────────────────────
    description = fields.Char(string='Description / Notes')
    notes = fields.Text(string='Notes')
    price = fields.Monetary(string='Estimated Price', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    mybiz_ref = fields.Char(string='myBiz Reference ID', readonly=True, copy=False)
    mybiz_status = fields.Selection([
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
        ('failed', 'Failed'),
    ], string='myBiz Status', default='pending', readonly=True)

    # ─── Flight / Train / Bus Fields ───────────────────────────────
    origin_code = fields.Char(
        string='Origin (City/Airport Code)',
        help='IATA airport code for flights (e.g. DEL, BOM) or city name for trains/bus.',
    )
    destination_code = fields.Char(
        string='Destination (City/Airport Code)',
    )
    departure_datetime = fields.Datetime(string='Departure Date & Time')
    arrival_datetime = fields.Datetime(string='Arrival Date & Time')
    operator = fields.Char(string='Airline / Carrier / Operator')
    travel_class = fields.Selection([
        ('economy', 'Economy'),
        ('premium_economy', 'Premium Economy'),
        ('business', 'Business'),
        ('first', 'First Class'),
        ('ac_1', '1st AC (Train)'),
        ('ac_2', '2nd AC (Train)'),
        ('ac_3', '3rd AC (Train)'),
        ('ac_chair', 'AC Chair Car'),
        ('sleeper', 'Sleeper'),
    ], string='Class / Category')
    pnr_or_booking_ref = fields.Char(
        string='PNR / Booking Reference',
        readonly=True, copy=False,
    )

    # ─── Hotel Fields ──────────────────────────────────────────────
    hotel_city = fields.Char(string='Hotel City')
    hotel_name = fields.Char(string='Hotel Name / Preference')
    hotel_grade = fields.Selection([
        ('3', '3 Star'),
        ('4', '4 Star'),
        ('5', '5 Star'),
        ('budget', 'Budget'),
    ], string='Hotel Grade')
    checkin_date = fields.Date(string='Check-in Date')
    checkout_date = fields.Date(string='Check-out Date')
    hotel_nights = fields.Integer(
        string='Nights',
        compute='_compute_hotel_nights',
        store=True,
    )
    rooms = fields.Integer(string='Rooms', default=1)

    @api.depends('checkin_date', 'checkout_date')
    def _compute_hotel_nights(self):
        for rec in self:
            if rec.checkin_date and rec.checkout_date and rec.checkout_date > rec.checkin_date:
                rec.hotel_nights = (rec.checkout_date - rec.checkin_date).days
            else:
                rec.hotel_nights = 0

    # ─── Cab Fields ────────────────────────────────────────────────
    cab_type = fields.Selection([
        ('sedan', 'Sedan'),
        ('suv', 'SUV'),
        ('hatchback', 'Hatchback'),
        ('tempo', 'Tempo Traveller'),
        ('any', 'Any'),
    ], string='Cab Type')
    pickup_location = fields.Char(string='Pickup Location')
    drop_location = fields.Char(string='Drop Location')
    pickup_datetime = fields.Datetime(string='Pickup Date & Time')