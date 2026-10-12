# -*- coding: utf-8 -*-
from odoo import api, fields, models


class BxiMybizAirport(models.Model):
    """MakeMyTrip's airport list ("Flight (IATA)" sheet of the myBiz code
    workbook). A flight leg's airportCode must be one of these codes; its
    cityName and cityCode are the city given here (DEL → New Delhi, CTDEL)."""
    _name = 'bxi.mybiz.airport'
    _description = 'MakeMyTrip Airport'
    _order = 'code'
    _rec_names_search = ['code', 'city', 'name']

    code = fields.Char(string='Airport Code', required=True, index=True)
    name = fields.Char(string='Airport', required=True)
    city = fields.Char(string='City')
    country_name = fields.Char(string='Country')
    timezone = fields.Char(string='Time Zone')
    city_code = fields.Char(
        string='MakeMyTrip City Code',
        help='MakeMyTrip code of the airport\'s city (DEL → CTDEL), sent as the '
             'flight leg\'s cityCode.')

    _code_unique = models.Constraint('UNIQUE(code)', 'Airport codes must be unique.')

    @api.depends('code', 'city', 'name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.code} – {rec.city or rec.name}'


class BxiMybizCity(models.Model):
    """MakeMyTrip's city list ("City Codes" and "Complete Dump" sheets of the
    myBiz code workbook). A hotel's cityCode must be one of these codes."""
    _name = 'bxi.mybiz.city'
    _description = 'MakeMyTrip City'
    _order = 'country_name, name'
    _rec_names_search = ['name', 'code']

    code = fields.Char(string='City Code', required=True, index=True)
    name = fields.Char(string='City', required=True, index=True)
    state_code = fields.Char(string='State Code')
    state_name = fields.Char(string='State')
    country_code = fields.Char(string='Country Code', index=True)
    country_name = fields.Char(string='Country')

    _code_unique = models.Constraint('UNIQUE(code)', 'City codes must be unique.')

    @api.depends('name', 'state_name', 'country_name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = ', '.join(filter(None, (rec.name, rec.state_name, rec.country_name)))

    @api.model
    def _match(self, name, country=None, state=None):
        """The city named `name` (any case) in `country`, using `state` to choose
        between same-named cities. Empty unless exactly one city matches."""
        if not name:
            return self.browse()
        domain = [('name', '=ilike', name.strip())]
        if country:
            # MakeMyTrip uses ISO-2 codes for India but mostly ISO-3 elsewhere.
            domain += ['|', ('country_code', '=', country.code),
                       ('country_name', '=ilike', country.name)]
        cities = self.search(domain)
        if len(cities) > 1 and state:
            cities = cities.filtered(
                lambda c: (c.state_name or '').lower() == state.name.lower())
        return cities if len(cities) == 1 else self.browse()
