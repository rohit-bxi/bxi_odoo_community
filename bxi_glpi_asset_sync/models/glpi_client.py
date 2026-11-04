# -*- coding: utf-8 -*-
"""
Thin client for the GLPI 11 High-Level REST API (``/api.php/v2``).

Authentication is the OAuth2 *password* grant: an OAuth client must be
registered in GLPI (Setup > OAuth Clients) with the "api" scope. Tokens are
cached per worker process until shortly before they expire.
"""
import logging
import re
import threading
import time

import requests

_logger = logging.getLogger(__name__)

USER_AGENT = 'Odoo-GLPI-Asset-Sync/19.0'
RETRY_DELAYS = (2, 5)
TOKEN_EXPIRY_MARGIN = 60

# Item types this module knows how to sync, with their API path and the
# GLPI web form used to build "Open in GLPI" links.
GLPI_ITEMTYPES = [
    ('Computer', 'Computer'),
    ('Printer', 'Printer'),
    ('Monitor', 'Monitor'),
    ('Peripheral', 'Peripheral'),
    ('Phone', 'Phone'),
    ('NetworkEquipment', 'Network Equipment'),
]
ITEMTYPE_PATHS = {code: f'/Assets/{code}' for code, _label in GLPI_ITEMTYPES}

# Hardware components summarised into the asset specs (Computer only).
COMPONENT_KINDS = ('Processor', 'Memory', 'HardDrive')

_token_cache = {}
_token_lock = threading.Lock()
_content_range_re = re.compile(r'(\d+)-(\d+)/(\d+)')


class GlpiError(Exception):
    """Any failure talking to GLPI (network, auth, HTTP >= 400)."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class GlpiClient:

    def __init__(self, config):
        """:param config: a sudo()-ed ``glpi.config`` record."""
        self.config = config
        self.base_url = (config.base_url or '').rstrip('/')
        if not self.base_url:
            raise GlpiError('The GLPI URL is not configured.')
        self.api_url = f"{self.base_url}/api.php/{config.api_version or 'v2'}"
        self.timeout = config.timeout or 30
        self.page_size = config.page_size or 100
        self.verify = config.verify_ssl
        self.session = requests.Session()
        # Never send the default python-requests User-Agent: some WAFs drop it.
        self.session.headers.update({
            'User-Agent': USER_AGENT,
            'Accept': 'application/json',
        })
        self._cache_key = (
            config.env.cr.dbname, config.id, self.base_url,
            config.client_id, config.username,
        )

    # ─── Authentication ──────────────────────────────────────────────────────

    def _fetch_token(self):
        cfg = self.config
        if not (cfg.client_id and cfg.client_secret and cfg.username and cfg.password):
            raise GlpiError('GLPI OAuth client ID/secret and username/password are required.')
        try:
            resp = self.session.post(
                f'{self.base_url}/api.php/token',
                data={
                    'grant_type': 'password',
                    'client_id': cfg.client_id,
                    'client_secret': cfg.client_secret,
                    'username': cfg.username,
                    'password': cfg.password,
                    'scope': cfg.scope or 'api',
                },
                timeout=self.timeout,
                verify=self.verify,
            )
        except requests.exceptions.RequestException as e:
            raise GlpiError(f'Cannot reach GLPI at {self.base_url}: {e}') from e
        if resp.status_code != 200:
            raise GlpiError(
                f'GLPI authentication failed (HTTP {resp.status_code}): {self._error_detail(resp)}',
                resp.status_code)
        payload = resp.json()
        token = payload.get('access_token')
        if not token:
            raise GlpiError('GLPI token response did not contain an access_token.')
        expires_in = int(payload.get('expires_in') or 3600)
        with _token_lock:
            _token_cache[self._cache_key] = (token, time.time() + expires_in - TOKEN_EXPIRY_MARGIN)
        return token

    def _token(self, force_refresh=False):
        if not force_refresh:
            with _token_lock:
                cached = _token_cache.get(self._cache_key)
            if cached and cached[1] > time.time():
                return cached[0]
        return self._fetch_token()

    # ─── Low-level request ───────────────────────────────────────────────────

    def _headers(self, token):
        headers = {'Authorization': f'Bearer {token}'}
        if self.config.entity_id:
            headers['GLPI-Entity'] = str(self.config.entity_id)
        headers['GLPI-Entity-Recursive'] = 'true' if self.config.entity_recursive else 'false'
        return headers

    def _request(self, method, path, params=None, payload=None):
        """Send a request, refreshing the token once on 401 and retrying
        network errors / 5xx responses. Returns the ``requests.Response``."""
        url = self.api_url + path
        token = self._token()
        refreshed = False
        attempt = 0
        while True:
            try:
                resp = self.session.request(
                    method, url, params=params, json=payload,
                    headers=self._headers(token), timeout=self.timeout, verify=self.verify)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < len(RETRY_DELAYS):
                    time.sleep(RETRY_DELAYS[attempt])
                    attempt += 1
                    continue
                raise GlpiError(f'Cannot reach GLPI ({method} {path}): {e}') from e
            if resp.status_code == 401 and not refreshed:
                token = self._token(force_refresh=True)
                refreshed = True
                continue
            if resp.status_code >= 500 and attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
                attempt += 1
                continue
            return resp

    def request(self, method, path, params=None, payload=None, allow_404=False):
        resp = self._request(method, path, params=params, payload=payload)
        if resp.status_code == 404 and allow_404:
            return None
        if resp.status_code >= 400:
            raise GlpiError(
                f'GLPI {method} {path} failed (HTTP {resp.status_code}): {self._error_detail(resp)}',
                resp.status_code)
        if not resp.content:
            return {}
        return resp.json()

    def get_all(self, path, params=None):
        """Fetch every page of a collection endpoint."""
        items = []
        start = 0
        while True:
            page_params = dict(params or {}, start=start, limit=self.page_size)
            resp = self._request('GET', path, params=page_params)
            if resp.status_code >= 400:
                raise GlpiError(
                    f'GLPI GET {path} failed (HTTP {resp.status_code}): {self._error_detail(resp)}',
                    resp.status_code)
            page = resp.json() if resp.content else []
            items.extend(page)
            start += len(page)
            total = self._total_from_range(resp.headers.get('Content-Range'))
            if not page or len(page) < self.page_size or (total is not None and start >= total):
                return items

    @staticmethod
    def _total_from_range(value):
        match = _content_range_re.search(value or '')
        return int(match.group(3)) if match else None

    @staticmethod
    def _error_detail(resp):
        try:
            body = resp.json()
        except ValueError:
            return (resp.text or '')[:300]
        if isinstance(body, dict):
            return (body.get('detail') or body.get('error_description')
                    or body.get('title') or body.get('error') or str(body))[:300]
        return str(body)[:300]

    # ─── Endpoints ───────────────────────────────────────────────────────────

    def count_assets(self, itemtype):
        resp = self._request('GET', ITEMTYPE_PATHS[itemtype], params={'start': 0, 'limit': 1})
        if resp.status_code >= 400:
            raise GlpiError(
                f'GLPI GET {ITEMTYPE_PATHS[itemtype]} failed (HTTP {resp.status_code}): '
                f'{self._error_detail(resp)}', resp.status_code)
        total = self._total_from_range(resp.headers.get('Content-Range'))
        return total if total is not None else len(resp.json() or [])

    def list_assets(self, itemtype):
        return self.get_all(ITEMTYPE_PATHS[itemtype])

    def get_infocom(self, itemtype, glpi_id):
        result = self.request('GET', f'{ITEMTYPE_PATHS[itemtype]}/{glpi_id}/Infocom', allow_404=True)
        return result if result and result.get('id') else None

    def get_components(self, glpi_id, kind):
        return self.request('GET', f'/Assets/Computer/{glpi_id}/Component/{kind}', allow_404=True) or []

    def list_users(self):
        return self.get_all('/Administration/User')

    def list_states(self):
        return self.get_all('/Dropdowns/State')

    def list_locations(self):
        return self.get_all('/Dropdowns/Location')

    def list_suppliers(self):
        return self.get_all('/Management/Supplier')

    def create_asset(self, itemtype, payload):
        result = self.request('POST', ITEMTYPE_PATHS[itemtype], payload=payload)
        return result.get('id')

    def update_asset(self, itemtype, glpi_id, payload):
        return self.request('PATCH', f'{ITEMTYPE_PATHS[itemtype]}/{glpi_id}', payload=payload)

    def create_infocom(self, itemtype, glpi_id, payload):
        result = self.request('POST', f'{ITEMTYPE_PATHS[itemtype]}/{glpi_id}/Infocom', payload=payload)
        return result.get('id')

    def update_infocom(self, itemtype, glpi_id, payload):
        return self.request('PATCH', f'{ITEMTYPE_PATHS[itemtype]}/{glpi_id}/Infocom', payload=payload)
