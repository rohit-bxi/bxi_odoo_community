# -*- coding: utf-8 -*-
import base64
import json
import string
from secrets import choice
from unittest.mock import MagicMock, patch

import requests
from Cryptodome.Cipher import AES, PKCS1_v1_5
from Cryptodome.Util.Padding import pad, unpad

from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .common import ICICICommon


def _encrypt_for(rsa_public_key, plaintext):
    """Build an ICICI-style encrypted envelope for ``plaintext``.

    Mirrors ``HrPayslip.encrypt_payload`` byte-for-byte so tests can
    fabricate responses that ``decrypt_response`` is able to decrypt.
    """
    aes_key = "".join(choice(string.digits) for _ in range(16))
    iv = "".join(choice(string.digits) for _ in range(16))
    encrypted_key = base64.b64encode(
        PKCS1_v1_5.new(rsa_public_key).encrypt(aes_key.encode("utf-8"))
    ).decode("utf-8")
    cipher = AES.new(aes_key.encode(), AES.MODE_CBC, iv.encode())
    cipher_text = cipher.encrypt(
        pad(plaintext.encode("utf-8"), AES.block_size)
    )
    encrypted_data = base64.b64encode(
        iv.encode("utf-8") + cipher_text
    ).decode("utf-8")
    return {"encryptedKey": encrypted_key, "encryptedData": encrypted_data}


@tagged('post_install', '-at_install')
class TestICICICrypto(ICICICommon):
    """Tests for the hybrid RSA/AES envelope and key-loading helpers."""

    def test_random_16_is_16_numeric_digits(self):
        value = self.env['hr.payslip'].random_16()
        self.assertEqual(len(value), 16)
        self.assertTrue(value.isdigit())

    def test_random_16_is_not_constant(self):
        payslip = self.env['hr.payslip']
        values = {payslip.random_16() for _ in range(20)}
        self.assertGreater(len(values), 1)

    def test_get_icici_public_key_missing_file_raises(self):
        self.patcher_icici_public_key.stop()
        try:
            with patch('os.path.isfile', return_value=False):
                with self.assertRaises(ValidationError):
                    self.env['hr.payslip'].get_icici_public_key()
        finally:
            self.patcher_icici_public_key.start()

    def test_environment_follows_base_url(self):
        payslip = self.env['hr.payslip']
        company = self.env.company

        company.icici_base_url = "https://apibankingone.icici.bank.in"
        self.assertEqual(
            payslip._get_icici_environment()["public_key"],
            "icici_public.pem",
        )

        company.icici_base_url = "https://apibankingonesandbox.icici.bank.in"
        self.assertEqual(
            payslip._get_icici_environment()["public_key"],
            "icici_public_sandbox.pem",
        )

    def test_get_icici_public_key_loads_key_of_environment(self):
        """Sandbox requests must not be encrypted with the production key."""
        payslip = self.env['hr.payslip']
        company = self.env.company

        self.patcher_icici_public_key.stop()
        try:
            company.icici_base_url = "https://apibankingone.icici.bank.in"
            production_key = payslip.get_icici_public_key()
            company.icici_base_url = (
                "https://apibankingonesandbox.icici.bank.in")
            sandbox_key = payslip.get_icici_public_key()
        finally:
            self.patcher_icici_public_key.start()

        self.assertFalse(production_key.has_private())
        self.assertFalse(sandbox_key.has_private())
        self.assertNotEqual(production_key.n, sandbox_key.n)

    def test_get_private_key_missing_file_raises(self):
        self.patcher_private_key.stop()
        try:
            with patch('os.path.isfile', return_value=False):
                with self.assertRaises(ValidationError):
                    self.env['hr.payslip'].get_private_key()
        finally:
            self.patcher_private_key.start()

    def test_encrypt_payload_roundtrip(self):
        payload = {"AGGRID": "BULK0173", "UNIQUEID": "ABC123"}
        encrypted = self.env['hr.payslip'].encrypt_payload(payload)

        self.assertEqual(encrypted["service"], "CIB")
        self.assertIn("encryptedKey", encrypted)
        self.assertIn("encryptedData", encrypted)

        # Decrypt as ICICI would, using the private half of icici_keypair.
        aes_key = PKCS1_v1_5.new(self.icici_keypair).decrypt(
            base64.b64decode(encrypted["encryptedKey"]), None,
        )
        raw = base64.b64decode(encrypted["encryptedData"])
        iv, cipher_text = raw[:16], raw[16:]
        cipher = AES.new(aes_key, AES.MODE_CBC, iv)
        decrypted = unpad(cipher.decrypt(cipher_text), AES.block_size)
        self.assertEqual(json.loads(decrypted.decode('utf-8')), payload)

    def test_decrypt_response_missing_encrypted_key_raises(self):
        with self.assertRaises(ValidationError):
            self.env['hr.payslip'].decrypt_response({"encryptedData": "x"})

    def test_decrypt_response_missing_encrypted_data_raises(self):
        with self.assertRaises(ValidationError):
            self.env['hr.payslip'].decrypt_response({"encryptedKey": "x"})

    def test_decrypt_response_invalid_base64_raises(self):
        with self.assertRaises(ValidationError):
            self.env['hr.payslip'].decrypt_response({
                "encryptedKey": "not-base64!!",
                "encryptedData": "also-not-base64!!",
            })

    def test_decrypt_response_json_body_returned_as_is(self):
        body = json.dumps({"RESPONSE": "SUCCESS"})
        envelope = _encrypt_for(self.client_keypair.publickey(), body)
        result = self.env['hr.payslip'].decrypt_response(envelope)
        self.assertEqual(json.loads(result), {"RESPONSE": "SUCCESS"})

    def test_decrypt_response_strips_16_byte_prefix(self):
        body = "1234567890ABCDEF" + json.dumps({"RESPONSE": "SUCCESS"})
        envelope = _encrypt_for(self.client_keypair.publickey(), body)
        result = self.env['hr.payslip'].decrypt_response(envelope)
        self.assertEqual(json.loads(result), {"RESPONSE": "SUCCESS"})


@tagged('post_install', '-at_install')
class TestICICIApiCall(ICICICommon):
    """Tests for ``call_icici_api``'s HTTP/retry/error handling."""

    def setUp(self):
        super().setUp()
        self.env.company.icici_api_key = "TEST-API-KEY"

    def _success_response(self, payload):
        envelope = _encrypt_for(
            self.client_keypair.publickey(), json.dumps(payload),
        )
        response = MagicMock(status_code=200)
        response.json.return_value = envelope
        return response

    @patch('odoo.addons.ICIC_bank.model.custom_payslip.requests.post')
    def test_call_icici_api_success_decrypts_response(self, mock_post):
        mock_post.return_value = self._success_response(
            {"RESPONSE": "SUCCESS"})

        result = self.env['hr.payslip'].call_icici_api(
            "https://example.invalid/api", {"UNIQUEID": "1"},
        )

        self.assertEqual(result["status_code"], 200)
        self.assertEqual(
            json.loads(result["response"]), {"RESPONSE": "SUCCESS"})

    @patch('odoo.addons.ICIC_bank.model.custom_payslip.requests.post')
    def test_call_icici_api_http_error_raises_with_body_message(
        self, mock_post,
    ):
        response = MagicMock(status_code=500)
        response.json.return_value = {"errormessage": "Bank is down"}
        response.text = '{"errormessage": "Bank is down"}'
        response.headers = {}
        mock_post.return_value = response

        with self.assertRaises(ValidationError) as capture:
            self.env['hr.payslip'].call_icici_api(
                "https://example.invalid/api", {"UNIQUEID": "1"},
            )
        self.assertIn("Bank is down", str(capture.exception))

    @patch('odoo.addons.ICIC_bank.model.custom_payslip.requests.post')
    def test_call_icici_api_invalid_json_raises(self, mock_post):
        response = MagicMock(status_code=200)
        response.json.side_effect = ValueError("bad json")
        mock_post.return_value = response

        with self.assertRaises(ValidationError):
            self.env['hr.payslip'].call_icici_api(
                "https://example.invalid/api", {"UNIQUEID": "1"},
            )

    @patch('odoo.addons.ICIC_bank.model.custom_payslip.requests.post')
    def test_call_icici_api_missing_encrypted_fields_raises(self, mock_post):
        response = MagicMock(status_code=200)
        response.json.return_value = {"foo": "bar"}
        mock_post.return_value = response

        with self.assertRaises(ValidationError):
            self.env['hr.payslip'].call_icici_api(
                "https://example.invalid/api", {"UNIQUEID": "1"},
            )

    @patch('odoo.addons.ICIC_bank.model.custom_payslip.requests.post')
    def test_call_icici_api_timeout_retries_then_raises(self, mock_post):
        mock_post.side_effect = requests.exceptions.ReadTimeout()

        with self.assertRaises(ValidationError):
            self.env['hr.payslip'].call_icici_api(
                "https://example.invalid/api", {"UNIQUEID": "1"},
            )
        self.assertEqual(mock_post.call_count, 3)

    @patch('odoo.addons.ICIC_bank.model.custom_payslip.requests.post')
    def test_call_icici_api_connection_error_retries_then_raises(
        self, mock_post,
    ):
        mock_post.side_effect = requests.exceptions.ConnectionError()

        with self.assertRaises(ValidationError):
            self.env['hr.payslip'].call_icici_api(
                "https://example.invalid/api", {"UNIQUEID": "1"},
            )
        self.assertEqual(mock_post.call_count, 3)

    @patch('odoo.addons.ICIC_bank.model.custom_payslip.requests.post')
    def test_call_icici_api_recovers_after_transient_timeout(self, mock_post):
        mock_post.side_effect = [
            requests.exceptions.ReadTimeout(),
            self._success_response({"RESPONSE": "SUCCESS"}),
        ]

        result = self.env['hr.payslip'].call_icici_api(
            "https://example.invalid/api", {"UNIQUEID": "1"},
        )
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(mock_post.call_count, 2)
