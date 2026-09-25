# -*- coding: utf-8 -*-
"""HDFC request encryption / response decryption.

HDFC shares the corporate API security specification (key wrapping, cipher mode,
IV placement, signature algorithm) only after onboarding. Implement these two
functions against that document; nothing else in the module depends on the scheme.
"""
from .client_base import HdfcClientError


def encrypt_request(config, payload):
    """:return: the request body to POST (dict)."""
    raise HdfcClientError(
        'HDFC encryption is not configured yet: the HDFC API security specification is pending.'
    )


def decrypt_response(config, body):
    """:return: the decrypted response (dict)."""
    raise HdfcClientError(
        'HDFC decryption is not configured yet: the HDFC API security specification is pending.'
    )
