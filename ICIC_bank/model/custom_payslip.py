import base64
import json
import logging
import os
import re
import string
import uuid
from datetime import datetime
from secrets import choice

import requests
from Cryptodome.Cipher import AES, PKCS1_v1_5
from Cryptodome.PublicKey import RSA
from Cryptodome.Util.Padding import pad, unpad

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

ICICI_PRODUCTION_URL = "https://apibankingone.icici.bank.in"

# ICICI sandbox and production gateways use different RSA keys, endpoint
# paths and test credentials. Encrypting a sandbox request with the
# production key makes ICICI reject it with "Decryption failed".
ICICI_ENVIRONMENTS = {
    "production": {
        "public_key": "icici_public.pem",
        "create_path": "/api/Corporate/CIB/v1/Create",
        "bulk_payment_path": "/api/v1/cibbulkpayment/bulkPayment",
        "reverse_path": "/api/v1/ReverseMis",
        "defaults": {
            "aggr_id": "BULK0173",
            "aggr_name": "BXITECH",
            "corp_id": "601902129",
            "user_id": "BALCHAND",
            "urn": "SR283346233",
            "debit_account": "693905601661",
            "debit_branch": "0011",
        },
    },
    "sandbox": {
        "public_key": "icici_public_sandbox.pem",
        "create_path": "/api/Corporate/CIB_SV/v1/Create",
        "bulk_payment_path": "/api/v1/cibbulkpayment_sv/bulkPayment",
        "reverse_path": "/api/v1/ReverseMis_sv",
        "defaults": {
            "aggr_id": "CIBBULK001",
            "aggr_name": "BULKTESTING",
            "corp_id": "TXBCORP2",
            "user_id": "USER2",
            "urn": "CIBTESTING",
            "debit_account": "000451000301",
            "debit_branch": "0011",
        },
    },
}


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    icici_payment_status = fields.Selection(
        [
            ("draft", "Draft"),
            ("otp_pending", "OTP Pending"),
            ("processing", "Processing"),
            ("paid", "Paid"),
            ("failed", "Failed"),
            ("reversed", "Reversed"),
        ],
        string="ICICI Payment Status",
        default="draft",
        copy=False,
    )

    icici_reference = fields.Char(
        string="ICICI Reference",
        copy=False,
        readonly=True,
        index=True,
    )

    icici_file_seq_num = fields.Char(
        string="File Sequence Number",
        copy=False,
        readonly=True,
        index=True,
    )

    icici_response = fields.Text(
        string="ICICI Response",
        copy=False,
        readonly=True,
    )

    icici_generated_otp = fields.Char(
        string="Generated OTP",
        copy=False,
    )

    icici_utr = fields.Char(
        string="UTR Number",
        copy=False,
        readonly=True,
        index=True,
    )

    # om_hr_payroll has no net_wage field of its own: net pay lives on the
    # payslip line whose salary rule code is "NET".
    net_wage = fields.Float(
        string="Net Wage",
        compute="_compute_net_wage",
        store=True,
    )

    _icici_public_key_cache = None
    _private_key_cache = None

    @api.depends("line_ids.total")
    def _compute_net_wage(self):
        for slip in self:
            slip.net_wage = slip.get_salary_line_total("NET")

    def _get_icici_param(self, key, default=""):
        """Fetch a company-dependent ICICI credential/config value.

        Falls back to the default of the active ICICI environment, so a
        sandbox setup never mixes in production identifiers.
        """
        company = self.company_id[:1] or self.env.company
        # Values pasted into Settings often carry stray spaces.
        value = (getattr(company, "icici_%s" % key, None) or "").strip()
        return (
            value
            or self._get_icici_environment()["defaults"].get(key)
            or default
        )

    def _get_icici_environment(self):
        """Return the ICICI environment settings matching the base URL."""
        company = self.company_id[:1] or self.env.company
        base_url = company.icici_base_url or ICICI_PRODUCTION_URL
        if "sandbox" in base_url.lower():
            return ICICI_ENVIRONMENTS["sandbox"]
        return ICICI_ENVIRONMENTS["production"]

    def random_16(self):
        """Generate a cryptographically secure 16-digit numeric string."""
        return "".join(
            choice(string.digits)
            for _ in range(16)
        )

    def get_icici_public_key(self):
        """Load and cache the ICICI public key of the active environment."""

        cls = type(self)
        key_file = self._get_icici_environment()["public_key"]
        cache = cls._icici_public_key_cache or {}

        if key_file in cache:
            return cache[key_file]

        key_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            key_file,
        )

        if not os.path.isfile(key_path):
            raise ValidationError(
                _("ICICI public key file %s not found.") % key_file
            )

        try:
            with open(key_path, "rb") as f:
                cache[key_file] = RSA.import_key(
                    f.read()
                )
            cls._icici_public_key_cache = cache

            _logger.info(
                "ICICI public key %s loaded successfully.",
                key_file,
            )

            return cache[key_file]

        except Exception as exc:
            _logger.exception(
                "Unable to load ICICI public key."
            )

            raise ValidationError(
                _("Unable to load ICICI public key.")
            ) from exc

    def get_private_key(self):
        """Load and cache the client private key."""

        cls = type(self)

        if cls._private_key_cache:
            return cls._private_key_cache

        module_path = os.path.abspath(
            os.path.dirname(__file__)
        )

        key_path = os.path.join(
            module_path,
            "..",
            "private_key.pem",
        )

        if not os.path.isfile(key_path):
            raise ValidationError(
                _("Private key file not found.")
            )

        try:
            with open(key_path, "rb") as file:
                cls._private_key_cache = RSA.import_key(
                    file.read()
                )

            return cls._private_key_cache

        except Exception as exc:
            _logger.exception(
                "Unable to load private key."
            )
            raise ValidationError(
                _("Unable to load private key.")
            ) from exc

    def encrypt_payload(self, payload):
        """Encrypt payload using ICICI Hybrid Encryption."""

        try:
            rsa_key = self.get_icici_public_key()

            json_payload = json.dumps(
                payload,
                separators=(",", ":"),
                ensure_ascii=False,
            )

            aes_key = self.random_16()
            iv = self.random_16()

            _logger.info("=" * 80)
            _logger.info("ICICI Payload Encryption Started")

            encrypted_key = base64.b64encode(
                PKCS1_v1_5.new(rsa_key).encrypt(
                    aes_key.encode("utf-8")
                )
            ).decode("utf-8")

            cipher = AES.new(
                aes_key.encode(),
                AES.MODE_CBC,
                iv.encode()
            )

            cipher_text = cipher.encrypt(
                pad(
                    json_payload.encode(),
                    AES.block_size
                )
            )

            # ICICI Option-B: IV prepended to ciphertext
            encrypted_data = base64.b64encode(
                iv.encode("utf-8") + cipher_text
            ).decode("utf-8")

            _logger.info(
                "ICICI Payload Encryption Completed."
            )

            return {
                # Keep empty, as in the bank-tested integration; a random
                # requestId coincided with ICICI error 8010.
                "requestId": "",
                "service": "CIB",
                "encryptedKey": encrypted_key,
                "oaepHashingAlgorithm": "NONE",
                "iv": "",
                "encryptedData": encrypted_data,
                "clientInfo": "",
                "optionalParam": "",
            }

        except Exception as exc:

            _logger.exception(
                "ICICI payload encryption failed."
            )

            raise ValidationError(
                _("Unable to encrypt ICICI request.")
            ) from exc

    def decrypt_response(self, response_data):
        """Decrypt ICICI encrypted response."""

        encrypted_key = response_data.get("encryptedKey")
        encrypted_data = response_data.get("encryptedData")

        if not encrypted_key:
            raise ValidationError(
                _("ICICI encrypted key is missing.")
            )

        if not encrypted_data:
            raise ValidationError(
                _("ICICI encrypted data is missing.")
            )

        try:

            private_key = self.get_private_key()

            aes_key = PKCS1_v1_5.new(
                private_key
            ).decrypt(
                base64.b64decode(encrypted_key),
                None,
            )

            if not aes_key or len(aes_key) != 16:
                raise ValidationError(
                    _("Invalid AES key received from ICICI.")
                )

            encrypted_bytes = base64.b64decode(
                encrypted_data,
                validate=True,
            )

            if len(encrypted_bytes) <= 16:
                raise ValidationError(
                    _("Invalid encrypted response received from ICICI.")
                )

            iv = encrypted_bytes[:16]
            cipher_text = encrypted_bytes[16:]

            cipher = AES.new(
                aes_key,
                AES.MODE_CBC,
                iv,
            )

            decrypted = unpad(
                cipher.decrypt(cipher_text),
                AES.block_size,
            )

            _logger.info(
                "FULL DECRYPTED RAW = %r",
                decrypted,
            )

            if len(decrypted) <= 16:
                raise ValidationError(
                    _("Invalid decrypted response received from ICICI.")
                )

            # ICICI specification:
            # Ignore first 16 bytes after decryption.
            full_response = decrypted.decode("utf-8")
            _logger.info(
                "FULL RESPONSE = %s",
                full_response,
            )

            if full_response.startswith("{"):
                return full_response

            return full_response[16:]

        except ValidationError:
            raise

        except UnicodeDecodeError as exc:

            raise ValidationError(
                _("Unable to decode ICICI response.")
            ) from exc

        except Exception as exc:

            _logger.exception(
                "Unable to decrypt ICICI response."
            )

            raise ValidationError(
                _("Unable to decrypt ICICI response.")
            ) from exc

    def call_icici_api(self, url, payload):
        """Call ICICI API using Hybrid Encryption."""

        api_key = self._get_icici_param("api_key")

        if not api_key:
            raise ValidationError(
                _(
                    "ICICI API Key is not configured. Please set it "
                    "under Settings > ICICI Bank."
                )
            )

        headers = {
            "accept": "*/*",
            "content-type": "application/json",
            "APIKEY": api_key,
        }

        encrypted_payload = self.encrypt_payload(payload)

        _logger.info("=" * 80)
        _logger.info("ICICI API CALL STARTED")
        _logger.info("URL : %s", url)
        _logger.info("REQUEST :\n%s", json.dumps(payload, indent=4))
        _logger.info("=" * 80)

        for attempt in range(1, 4):

            try:
                _logger.info(
                    json.dumps(
                        encrypted_payload,
                        indent=4
                    )
                )
                response = requests.post(
                    url=url,
                    headers=headers,
                    json=encrypted_payload,
                    timeout=(10, 60),
                )

                _logger.info(
                    "HTTP STATUS : %s",
                    response.status_code,
                )

                if response.status_code != 200:

                    _logger.error("=" * 80)
                    _logger.error("ICICI HTTP ERROR")
                    _logger.error(
                        "Status Code : %s",
                        response.status_code,
                    )
                    _logger.error(
                        "Headers : %s",
                        dict(response.headers),
                    )
                    _logger.error(
                        "Body : %s",
                        response.text,
                    )
                    _logger.error("=" * 80)

                    try:
                        error_json = response.json()

                        error_message = (
                            error_json.get("errormessage")
                            or error_json.get("message")
                            or error_json.get("MESSAGE")
                            or response.text
                        )

                        error_code = (
                            error_json.get("errorcode")
                            or error_json.get("errorCode")
                            or error_json.get("ERRORCODE")
                            # e.g. {"response": 8017, "errormessage": ...}
                            or error_json.get("response")
                        )

                    except Exception:
                        error_message = response.text
                        error_code = None

                    if error_code:
                        raise ValidationError(
                            _("ICICI API Error [%s] (HTTP %s):\n%s")
                            % (error_code, response.status_code, error_message)
                        )

                    raise ValidationError(
                        _("ICICI API Error (HTTP %s):\n%s")
                        % (response.status_code, error_message)
                    )

                try:
                    response_json = response.json()

                except ValueError as exc:

                    _logger.exception(
                        "Invalid JSON received from ICICI."
                    )

                    raise ValidationError(
                        _("Invalid JSON received from ICICI.")
                    ) from exc

                if (
                    "encryptedKey" not in response_json
                    or "encryptedData" not in response_json
                ):
                    raise ValidationError(
                        _("Encrypted response not received from ICICI.")
                    )

                decrypted_response = self.decrypt_response(
                    response_json
                )

                _logger.info("=" * 80)
                _logger.info("ICICI API SUCCESS")
                _logger.info(
                    "RESPONSE : %s",
                    decrypted_response,
                )
                _logger.info("=" * 80)

                return {
                    "status_code": response.status_code,
                    "response": decrypted_response,
                }

            except requests.exceptions.ReadTimeout:

                _logger.warning(
                    "ICICI timeout (%s/3)",
                    attempt,
                )

                if attempt == 3:
                    raise ValidationError(
                        _(
                            "ICICI server timed out. Please try again."
                        )
                    )

            except requests.exceptions.ConnectionError as exc:

                _logger.exception(
                    "Unable to connect to ICICI."
                )

                if attempt == 3:
                    raise ValidationError(
                        _(
                            "Unable to connect to the ICICI server."
                        )
                    ) from exc

            except ValidationError:
                raise

            except Exception as exc:

                _logger.exception(
                    "Unexpected ICICI API error."
                )

                raise ValidationError(
                    _(
                        "Unexpected error occurred while "
                        "communicating with ICICI."
                    )
                ) from exc

        raise ValidationError(
            _("Unable to process the ICICI request.")
        )

    def _get_icici_base_url(self):
        base_url = self._get_icici_param(
            "base_url", ICICI_PRODUCTION_URL
        ).rstrip("/")

        if not base_url:
            raise ValidationError(
                _(
                    "ICICI Base URL is not configured. Please set it "
                    "under Settings > ICICI Bank."
                )
            )

        return base_url

    def action_release_salary(self):
        """Validate payslips, call ICICI Create API and open OTP wizard."""

        if not self:
            raise ValidationError(
                _("No payslips selected.")
            )
        for slip in self:

            if slip.icici_payment_status in (
                "otp_pending",
                "processing",
                "paid",
            ):
                raise ValidationError(
                    _(
                        "Salary payment has already been initiated for %s."
                    )
                    % slip.employee_id.name
                )

            if slip.state != "done":
                raise ValidationError(
                    _(
                        "%s payslip must be confirmed before salary "
                        "release."
                    )
                    % slip.employee_id.name
                )

            employee = slip.employee_id

            bank_account = employee.bank_account_ids.filtered(
                lambda account:
                    account.acc_number
                    and account.bank_id
                    and account.bank_id.bic
            )[:1]

            if not bank_account:
                raise ValidationError(
                    _(
                        "Please configure a valid bank account for %s."
                    )
                    % employee.name
                )

            if not bank_account.acc_number:
                raise ValidationError(
                    _("Account Number is missing for %s.")
                    % employee.name
                )

            if not bank_account.bank_id:
                raise ValidationError(
                    _("Bank is not configured for %s.")
                    % employee.name
                )

            if not bank_account.bank_id.bic:
                raise ValidationError(
                    _("IFSC Code is missing for %s.")
                    % employee.name
                )

            amount = float(slip.net_wage or 0.0)

            if amount <= 0:
                raise ValidationError(
                    _("Invalid salary amount for %s.")
                    % employee.name
                )

        # ------------------------------------------------------------------
        # Generate Unique Reference
        # ------------------------------------------------------------------

        unique_id = uuid.uuid4().hex[:16].upper()

        while self.search_count([
            ("icici_reference", "=", unique_id)
        ]):
            unique_id = uuid.uuid4().hex[:16].upper()

        create_payload = {
            "AGGRID": self._get_icici_param("aggr_id"),
            "AGGRNAME": self._get_icici_param("aggr_name"),
            "CORPID": self._get_icici_param("corp_id"),
            "USERID": self._get_icici_param("user_id"),
            "URN": self._get_icici_param("urn"),
            "UNIQUEID": unique_id,
        }

        _logger.info("=" * 80)
        _logger.info("ICICI CREATE API REQUEST")
        _logger.info(json.dumps(create_payload, indent=4))
        _logger.info("=" * 80)

        result = self.call_icici_api(
            self._get_icici_base_url()
            + self._get_icici_environment()["create_path"],
            create_payload,
        )

        response = (result.get("response") or "").strip()

        if not response:
            raise ValidationError(
                _("Empty response received from ICICI.")
            )

        json_start = response.find("{")
        json_end = response.rfind("}")

        if json_start == -1 or json_end == -1:
            raise ValidationError(
                _("Invalid response received from ICICI.\n\n%s")
                % response
            )

        clean_response = response[
            json_start: json_end + 1
        ]

        try:
            response_json = json.loads(clean_response)

        except Exception as exc:
            _logger.exception(
                "Unable to parse ICICI Create response."
            )

            raise ValidationError(
                _("Unable to parse ICICI Create API response.")
            ) from exc

        _logger.info("=" * 80)
        _logger.info("ICICI CREATE RESPONSE")
        _logger.info(
            json.dumps(response_json, indent=4)
        )
        _logger.info("=" * 80)

        response_status = (
            response_json.get("RESPONSE")
            or response_json.get("Response")
            or ""
        ).strip().upper()

        if response_status != "SUCCESS":
            raise ValidationError(
                response_json.get("MESSAGE")
                or response_json.get("Message")
                or _("ICICI Create API failed.")
            )

        otp = (
            response_json.get("OTP")
            or response_json.get("otp")
            or response_json.get("AgOtp")
        )

        vals = {
            "icici_reference": unique_id,
            "icici_payment_status": "otp_pending",
        }

        if otp:
            vals["icici_generated_otp"] = otp

        self.write(vals)

        if otp:
            _logger.info(
                "OTP received from ICICI Create API."
            )
        else:
            _logger.info(
                "OTP has been sent to the authorized ICICI user."
            )

        return {
            "type": "ir.actions.act_window",
            "name": _("ICICI OTP Verification"),
            "res_model": "icici.otp.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_payslip_ids": self.ids,
            },
        }

    def generate_salary_file(self, payment_date):
        """Generate ICICI Salary File."""
        payment_date = fields.Date.to_date(
            payment_date
        ).strftime("%m/%d/%Y")

        debit_account = self._get_icici_param(
            "debit_account"
        )
        debit_branch = self._get_icici_param(
            "debit_branch"
        )

        transaction_count = 0
        total_amount = 0.00
        detail_lines = []

        for slip in self:

            employee = slip.employee_id

            bank_account = employee.bank_account_ids.filtered(
                lambda account:
                    account.acc_number
                    and account.bank_id
                    and account.bank_id.bic
            )[:1]

            if not bank_account:
                raise ValidationError(
                    _("Bank account is missing for %s.")
                    % employee.name
                )

            account_number = (
                bank_account.acc_number or ""
            ).strip()

            if not account_number:
                raise ValidationError(
                    _("Account Number is missing for %s.")
                    % employee.name
                )

            if len(account_number) < 9:
                raise ValidationError(
                    _("Invalid Account Number for %s.")
                    % employee.name
                )

            ifsc = (
                bank_account.bank_id.bic or ""
            ).strip().upper()

            if len(ifsc) != 11:
                raise ValidationError(
                    _("Invalid IFSC Code for %s.")
                    % employee.name
                )

            if not ifsc[:4].isalpha():
                raise ValidationError(
                    _("Invalid IFSC Code for %s.")
                    % employee.name
                )

            amount = round(
                float(slip.net_wage or 0.0),
                2,
            )

            if amount <= 0:
                raise ValidationError(
                    _("Invalid salary amount for %s.")
                    % employee.name
                )

            transaction_count += 1
            total_amount += amount

            # Branch 0011 / ICIC0000011 is the format ICICI accepted in
            # production testing for within-bank (MCW) transfers.
            if ifsc.startswith("ICIC"):
                transaction_type = "MCW"
                network = "WIB"
                branch_code = "0011"
                beneficiary_ifsc = "ICIC0000011"
            else:
                transaction_type = "MCO"
                network = "NFT"
                branch_code = "0011"
                beneficiary_ifsc = ifsc

            employee_name = " ".join(
                employee.name.split()
            )[:35]

            detail_line = "|".join([
                transaction_type,
                account_number,
                branch_code,
                employee_name,
                f"{amount:.2f}",
                "INR",
                "Salary",
                network,
                beneficiary_ifsc,
            ]) + "^"

            detail_lines.append(detail_line)

            _logger.info(
                "Employee : %s | Type : %s | Amount : %.2f | IFSC : %s",
                employee.name,
                transaction_type,
                amount,
                beneficiary_ifsc,
            )

        if transaction_count == 0:
            raise ValidationError(
                _("No valid payslips found.")
            )

        header = (
            # The record count includes the MDR line.
            f"FHR|{transaction_count + 1}|"
            f"{payment_date}|"
            f"SALARY|"
            f"{total_amount:.2f}|"
            f"INR|"
            f"{debit_account}|"
            f"{debit_branch}^"
        )

        maker = (
            f"MDR|"
            f"{debit_account}|"
            f"{debit_branch}|"
            f"SALARY|"
            f"{total_amount:.2f}|"
            f"INR|"
            f"Salary Batch|"
            f"ICIC0{debit_branch.zfill(6)}|"
            f"WIB^"
        )

        salary_file = "\r\n".join(
            [header, maker] + detail_lines
        )

        _logger.info("=" * 80)
        _logger.info("ICICI SALARY FILE GENERATED")
        _logger.info("\n%s", salary_file)
        _logger.info("=" * 80)

        return salary_file

    def action_reverse_payment(self, file_seq_num):
        """Reverse an ICICI salary payment."""

        self.ensure_one()

        if not file_seq_num:
            raise ValidationError(
                _("File Sequence Number is required.")
            )

        if not self.icici_reference:
            raise ValidationError(
                _("ICICI Reference is missing.")
            )

        if self.icici_payment_status != "processing":
            raise ValidationError(
                _("Only payments in Processing state can be reversed.")
            )

        corp_id = self._get_icici_param("corp_id")
        user_id = self._get_icici_param("user_id")

        # ReverseMis expects the fully qualified "CORPID.USERID" login.
        if "." not in user_id:
            user_id = "%s.%s" % (corp_id, user_id)

        payload = {
            "AGGRID": self._get_icici_param("aggr_id"),
            "CORPID": corp_id,
            "USERID": user_id,
            "URN": self._get_icici_param("urn"),
            "FILESEQNUM": file_seq_num,
            "UNIQUEID": self.icici_reference,
            "ISENCRYPTED": "N",
        }

        _logger.info("=" * 80)
        _logger.info("ICICI REVERSE PAYMENT REQUEST")
        _logger.info(
            json.dumps(payload, indent=4)
        )
        _logger.info("=" * 80)

        result = self.call_icici_api(
            self._get_icici_base_url()
            + self._get_icici_environment()["reverse_path"],
            payload,
        )

        response = (result.get("response") or "").strip()

        if not response:
            raise ValidationError(
                _("Empty response received from ICICI.")
            )

        json_start = response.find("{")
        json_end = response.rfind("}")

        if json_start == -1 or json_end == -1:
            raise ValidationError(
                _("Invalid response received from ICICI.\n\n%s")
                % response
            )

        clean_response = response[
            json_start: json_end + 1
        ]

        try:
            response_json = json.loads(
                clean_response
            )

        except Exception as exc:

            _logger.exception(
                "Unable to parse ICICI Reverse API response."
            )

            raise ValidationError(
                _("Unable to parse ICICI Reverse API response.")
            ) from exc

        _logger.info("=" * 80)
        _logger.info("ICICI REVERSE RESPONSE")
        _logger.info(
            json.dumps(response_json, indent=4)
        )
        _logger.info("=" * 80)

        # Some ICICI APIs return XML object,
        # some return direct JSON.
        response_data = (
            response_json.get("XML")
            or response_json
        )

        response_status = (
            response_data.get("RESPONSE")
            or response_data.get("Response")
            or ""
        ).strip().upper()

        if response_status != "SUCCESS":
            raise ValidationError(
                response_data.get("MESSAGE")
                or response_data.get("Message")
                or _("Reverse payment failed.")
            )

        self.write({
            "icici_payment_status": "reversed",
            "icici_response": json.dumps(
                response_json,
                indent=4,
            ),
            "icici_generated_otp": False,
            "icici_file_seq_num": False,
            "icici_utr": False,
        })

        _logger.info(
            "ICICI payment reversed successfully."
        )

        return True

    def process_bulk_payment(self, otp, payment_date):
        """Submit salary file to ICICI after OTP verification."""

        if not self:
            raise ValidationError(
                _("No payslips selected.")
            )

        otp = (otp or "").strip()

        if not otp:
            raise ValidationError(
                _("Please enter the OTP.")
            )

        for slip in self:

            if slip.icici_payment_status != "otp_pending":
                raise ValidationError(
                    _(
                        "Salary payment is not awaiting OTP for %s."
                    )
                    % slip.employee_id.name
                )

            if not slip.icici_reference:
                raise ValidationError(
                    _(
                        "ICICI Reference is missing for %s."
                    )
                    % slip.employee_id.name
                )

        salary_file = self.generate_salary_file(
            payment_date
        )

        encoded_file = base64.b64encode(
            salary_file.encode("utf-8")
        ).decode("utf-8")

        payload = {
            "FILE_DESCRIPTION": "Salary Payment",
            "AGGR_ID": self._get_icici_param("aggr_id"),
            "URN": self._get_icici_param("urn"),
            "AGGR_NAME": self._get_icici_param("aggr_name"),
            "USER_ID": self._get_icici_param("user_id"),
            "CORP_ID": self._get_icici_param("corp_id"),
            "UNIQUE_ID": self[0].icici_reference,
            "AGOTP": otp,
            "FILE_NAME": (
                f"SALARY_"
                f"{datetime.now().strftime('%Y%m%d%H%M%S')}.txt"
            ),
            "FILE_CONTENT": encoded_file,
        }

        _logger.info("=" * 80)
        _logger.info("ICICI BULK PAYMENT REQUEST")
        _logger.info(
            json.dumps(payload, indent=4)
        )
        _logger.info("=" * 80)

        result = self.call_icici_api(
            self._get_icici_base_url()
            + self._get_icici_environment()["bulk_payment_path"],
            payload,
        )

        response = (
            result.get("response") or ""
        ).strip()

        if not response:
            raise ValidationError(
                _("Empty response received from ICICI.")
            )

        json_start = response.find("{")
        json_end = response.rfind("}")

        if json_start == -1 or json_end == -1:
            raise ValidationError(
                _(
                    "Invalid response received from ICICI.\n\n%s"
                )
                % response
            )

        clean_response = response[
            json_start: json_end + 1
        ]

        try:

            response_json = json.loads(
                clean_response
            )

        except Exception as exc:

            _logger.exception(
                "Unable to parse ICICI Bulk Payment response."
            )

            raise ValidationError(
                _(
                    "Unable to parse ICICI Bulk Payment response."
                )
            ) from exc

        _logger.info("=" * 80)
        _logger.info("ICICI BULK PAYMENT RESPONSE")
        _logger.info(
            json.dumps(
                response_json,
                indent=4,
            )
        )
        _logger.info("=" * 80)

        response_status = (
            response_json.get("RESPONSE")
            or response_json.get("Response")
            or response_json.get("response")
            or response_json.get("status")
            or response_json.get("Status")
            or ""
        ).strip().upper()

        message = (
            response_json.get("MESSAGE_DESC")
            or response_json.get("MESSAGE")
            or response_json.get("Message")
            or response_json.get("message")
            or ""
        )

        is_success = (
            response_status == "SUCCESS"
            or "SUCCESSFULLY" in message.upper()
            or "SUCCESS" in message.upper()
        )

        if not is_success:
            raise ValidationError(
                message or _("ICICI Bulk Payment failed.")
            )

        file_sequence = (
            response_json.get("FILE_SEQUENCE_NUM")
            or response_json.get("FILESEQNUM")
            or ""
        )

        if not file_sequence and message:
            match = re.search(
                r"File Sequence\s*(?:No|Number)?\s*:\s*\[?(\d+)\]?",
                message,
                re.IGNORECASE,
            )
            if match:
                file_sequence = match.group(1)

        utr = (
            response_json.get("UTR")
            or response_json.get("UTR_NUMBER")
            or ""
        )

        self.write({
            "icici_payment_status": "processing",
            "icici_generated_otp": False,
            "icici_file_seq_num": file_sequence,
            "icici_utr": utr,
            "icici_response": json.dumps(
                response_json,
                indent=4,
            ),
        })

        _logger.info("=" * 80)
        _logger.info(
            "ICICI BULK PAYMENT SUBMITTED SUCCESSFULLY"
        )
        _logger.info(
            "FILE SEQUENCE : %s",
            file_sequence,
        )
        _logger.info(
            "UTR : %s",
            utr,
        )
        _logger.info("=" * 80)

        return True

    def action_open_reverse_wizard(self):
        """Open ICICI Reverse Payment Wizard."""

        self.ensure_one()

        if self.icici_payment_status != "processing":
            raise ValidationError(
                _(
                    "Only payments in Processing state can be reversed."
                )
            )

        if not self.icici_file_seq_num:
            raise ValidationError(
                _("File Sequence Number is not available.")
            )

        return {
            "type": "ir.actions.act_window",
            "name": _("Reverse Payment"),
            "res_model": "icici.reverse.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_payslip_id": self.id,
                "default_file_seq_num": self.icici_file_seq_num,
            },
        }
