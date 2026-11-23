# -*- coding: utf-8 -*-
"""Lookups for the codes MakeMyTrip myBiz expects in a travel request.

FLIGHT journeys need a 3-letter IATA ``airportCode`` and HOTEL services need
MMT's own ``cityCode`` (e.g. ``CTDEL``). Users type city names, so both are
resolved from MMT's code list ("IATA And City codes.xlsx"), shipped as CSV
under ``data/mmt/``.
"""
import csv
import functools
import re

from odoo.tools import file_open

AIRPORTS_CSV = 'bxi_mybiz_integration/data/mmt/airports.csv'
CITIES_CSV = 'bxi_mybiz_integration/data/mmt/cities.csv'

# Common alternate spellings -> the name MMT's airport list uses.
AIRPORT_CITY_ALIASES = {
    'delhi': 'new delhi',
    'bangalore': 'bengaluru',
    'bombay': 'mumbai',
    'madras': 'chennai',
    'calcutta': 'kolkata',
    'trivandrum': 'thiruvananthapuram',
    'cochin': 'kochi',
    'vizag': 'visakhapatnam',
    'thoothukudi': 'tuticorin',
    # Cities with no airport of their own -> the airport travellers use.
    'delhi ncr': 'new delhi',
    'noida': 'new delhi',
    'greater noida': 'new delhi',
    'gurgaon': 'new delhi',
    'gurugram': 'new delhi',
    'faridabad': 'new delhi',
    'aerocity': 'new delhi',
    'aero city': 'new delhi',
    'gandhinagar': 'ahmedabad',
    'ghandhi nagar': 'ahmedabad',
    'gandhi nagar': 'ahmedabad',
    'secunderabad': 'hyderabad',
}
# Same idea for MMT's hotel city list.
HOTEL_CITY_ALIASES = {
    'new delhi': 'delhi',
    'bengaluru': 'bangalore',
    'bombay': 'mumbai',
    'madras': 'chennai',
    'calcutta': 'kolkata',
    'gurugram': 'gurgaon',
}

_CITY_CODE_RE = re.compile(r'^CT[A-Z0-9]{2,}$')


def _norm(value):
    return re.sub(r'\s+', ' ', (value or '').strip()).lower()


@functools.lru_cache(maxsize=1)
def _airports():
    """Return ({IATA: row}, {normalised city: [rows]})."""
    by_code, by_city = {}, {}
    with file_open(AIRPORTS_CSV, 'r') as fh:
        for row in csv.DictReader(fh):
            by_code[row['airport_code']] = row
            by_city.setdefault(_norm(row['city']), []).append(row)
    return by_code, by_city


@functools.lru_cache(maxsize=1)
def _cities():
    """Return ({MMT city code: row}, {normalised city name: [rows]})."""
    by_code, by_name = {}, {}
    with file_open(CITIES_CSV, 'r') as fh:
        for row in csv.DictReader(fh):
            by_code[row['city_code']] = row
            by_name.setdefault(_norm(row['city']), []).append(row)
    return by_code, by_name


def _pick(rows, country_name):
    """Prefer a match in the expected country, then a city-wide code, then an
    international airport; otherwise the first row."""
    def rank(row):
        name = row.get('airport_name', '').lower()
        return (
            0 if country_name and _norm(row['country']) == _norm(country_name) else 1,
            0 if name == 'all airports' else 1,
            0 if 'international' in name else 1,
        )
    return min(rows, key=rank) if rows else None


def resolve_airport_code(value, country_name=None):
    """Map an IATA code or a city name to a 3-letter IATA code, or None."""
    raw = (value or '').strip()
    if not raw:
        return None
    by_code, by_city = _airports()
    # An explicit upper-case code wins ("GOA" is Genoa; "Goa" is the city).
    if len(raw) == 3 and raw.isalpha() and raw.isupper() and raw in by_code:
        return raw
    # "Aero city, New delhi": try the whole text, then each comma part from the end.
    candidates = [raw] + [p for p in reversed(raw.split(',')) if p.strip()] if ',' in raw else [raw]
    for part in candidates:
        key = _norm(part)
        row = _pick(by_city.get(key) or by_city.get(AIRPORT_CITY_ALIASES.get(key, '')) or [],
                    country_name)
        if row:
            return row['airport_code']
    if len(raw) == 3 and raw.isalpha() and raw.upper() in by_code:
        return raw.upper()
    return None


def resolve_city_code(value, country_name=None):
    """Map a city name (or an MMT city code) to (city_code, city_name), or None."""
    raw = (value or '').strip()
    if not raw:
        return None
    by_code, by_name = _cities()
    if _CITY_CODE_RE.match(raw) and raw in by_code:
        return raw, by_code[raw]['city']
    key = _norm(raw)
    row = _pick(by_name.get(key) or by_name.get(HOTEL_CITY_ALIASES.get(key, '')) or [],
                country_name)
    return (row['city_code'], row['city']) if row else None
