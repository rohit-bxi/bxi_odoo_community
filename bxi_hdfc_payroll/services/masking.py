# -*- coding: utf-8 -*-
import json

SECRET_KEYS = {
    'otp', 'agotp', 'password', 'client_secret', 'api_key', 'apikey', 'authorization',
    'access_token', 'refresh_token', 'private_key', 'encryptedkey', 'encrypteddata',
    'file_content', 'content', 'signature',
}
ACCOUNT_KEYS = {
    'account_number', 'acc_number', 'beneficiary_account', 'debit_account_number',
    'debit_account', 'accountno', 'account_no',
}


def mask_account(value):
    """Keep only the last four characters of an account number."""
    value = str(value or '')
    if len(value) <= 4:
        return '****'
    return '*' * (len(value) - 4) + value[-4:]


def mask_payload(data):
    """Return a copy of ``data`` with secrets removed and account numbers masked."""
    if isinstance(data, dict):
        masked = {}
        for key, value in data.items():
            normalized = str(key).lower()
            if normalized in SECRET_KEYS:
                masked[key] = '***'
            elif normalized in ACCOUNT_KEYS:
                masked[key] = mask_account(value)
            else:
                masked[key] = mask_payload(value)
        return masked
    if isinstance(data, (list, tuple)):
        return [mask_payload(item) for item in data]
    if isinstance(data, bytes):
        return '<%d bytes>' % len(data)
    return data


def to_log_text(data):
    if data is None:
        return False
    return json.dumps(mask_payload(data), indent=2, default=str, ensure_ascii=False)
