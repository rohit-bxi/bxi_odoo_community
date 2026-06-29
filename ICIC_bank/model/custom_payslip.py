from odoo.fields import Date

from odoo import models, fields
from odoo.exceptions import ValidationError

import os
import json
import base64
import random
import string
import logging
import requests
import uuid

from Crypto.PublicKey import RSA
from Crypto.Cipher import AES
from Crypto.Cipher import PKCS1_v1_5
from Crypto.Util.Padding import pad, unpad


_logger = logging.getLogger(__name__)


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    icici_payment_status = fields.Selection([
        ('draft', 'Draft'),
        ('otp_pending', 'OTP Pending'),
        ('processing', 'Processing'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('reversed', 'Reversed'),
    ], default='draft')

    icici_reference = fields.Char()
    icici_file_seq_num = fields.Char()
    icici_response = fields.Text()
    icici_generated_otp = fields.Char()
    icici_utr = fields.Char()

    def random_16(self):

        return ''.join(
            random.choices(
                string.digits,
                k=16
            )
        )

    _icici_public_key_cache = None
    def get_icici_public_key(self):
        cls = type(self)
        if cls._icici_public_key_cache:
            return cls._icici_public_key_cache
        module_path = os.path.dirname(__file__)
        public_key_path = os.path.join(
            module_path,
            '..',
            'icici_public.pem'
        )
        with open(public_key_path, 'rb') as f:
            key_data = f.read()
        cls._icici_public_key_cache = RSA.import_key(
            key_data
        )
        return cls._icici_public_key_cache

    _private_key_cache = None

    def get_private_key(self):
        cls = type(self)
        if cls._private_key_cache:
            return cls._private_key_cache
        module_path = os.path.dirname(__file__)
        private_key_path = os.path.join(
            module_path,
            '..',
            'private_key.pem'
        )
        with open(private_key_path, 'rb') as f:
            key_data = f.read()
        cls._private_key_cache = RSA.import_key(
            key_data
        )
        return cls._private_key_cache

    def encrypt_payload(self, payload):

        rsa_key = self.get_icici_public_key()

        json_data = json.dumps(
            payload,
            separators=(',', ':'),
            ensure_ascii=False
        )

        randomno1 = self.random_16()

        cipher_rsa = PKCS1_v1_5.new(
            rsa_key
        )

        encrypted_key = cipher_rsa.encrypt(
            randomno1.encode()
        )

        encr_key_b64 = base64.b64encode(
            encrypted_key
        ).decode()

        randomno2 = self.random_16()

        data = randomno2 + json_data

        cipher_aes = AES.new(
            randomno1.encode(),
            AES.MODE_CBC,
            iv=randomno2.encode()
        )

        encrypted_data = cipher_aes.encrypt(
            pad(
                data.encode(),
                AES.block_size
            )
        )

        encr_data_b64 = base64.b64encode(
            encrypted_data
        ).decode()

        return {
            'requestId': '',
            'service': 'CIB',
            'encryptedKey': encr_key_b64,
            'oaepHashingAlgorithm': 'NONE',
            'iv': '',
            'encryptedData': encr_data_b64,
            'clientInfo': '',
            'optionalParam': ''
        }

    def decrypt_response(self, response_data):
        encrypted_key = response_data.get(
            'encryptedKey'
        )
        encrypted_data = response_data.get(
            'encryptedData'
        )
        private_key = self.get_private_key()
        encrypted_key_bytes = base64.b64decode(
            encrypted_key
        )
        _logger.info(
            'Encrypted key length: %s',
            len(encrypted_key_bytes)
        )
        cipher_rsa = PKCS1_v1_5.new(
            private_key
        )
        aes_key = cipher_rsa.decrypt(
            encrypted_key_bytes,
            None
        )
        encrypted_data_bytes = base64.b64decode(
            encrypted_data
        )
        iv = encrypted_data_bytes[:16]
        cipher_aes = AES.new(
            aes_key,
            AES.MODE_CBC,
            iv=iv
        )
        try:
            decrypted = unpad(
                cipher_aes.decrypt(
                    encrypted_data_bytes
                ),
                AES.block_size
            )
        except Exception:
            raise ValidationError(
                'ICICI decryption failed.'
            )
        final_response = decrypted[16:]
        return final_response.decode()

    def call_icici_api(self, url, payload):
        headers = {
            'accept': '*/*',
            'content-type': 'application/json',
            'APIKEY': 'HLAo88SpqGCpnwW87KcdwElPsfhPGVyG'
        }
        response = None
        try:

            encrypted_payload = self.encrypt_payload(
                payload
            )

            _logger.info(
                'ICICI API CALL STARTED'
            )

            for attempt in range(3):
                _logger.info(
                    'ICICI REQUEST URL: %s',
                    url
                )

                _logger.info(
                    'ICICI REQUEST BODY: %s',
                    encrypted_payload
                )

                try:

                    response = requests.post(
                        url,
                        headers=headers,
                        json=encrypted_payload,
                        timeout=(10, 60)
                    )
                    _logger.info(
                        'ICICI RAW RESPONSE: %s',
                        response.text
                    )

                    break

                except requests.exceptions.ReadTimeout:

                    _logger.warning(
                        'ICICI timeout retry %s',
                        attempt + 1
                    )

                    if attempt == 2:

                        raise ValidationError(
                            'ICICI server timeout. Please try again.'
                        )

            if response is None:

                raise ValidationError(
                    'No response from ICICI.'
                )

            _logger.info(
                'ICICI STATUS CODE: %s',
                response.status_code
            )

            if response.status_code != 200:

                try:

                    error_response = response.json()

                    error_message = (
                        error_response.get('errormessage')
                        or error_response.get('message')
                        or response.text
                    )

                except Exception:

                    error_message = response.text

                raise ValidationError(
                    f'ICICI API Error:\n{error_message}'
                )

            response_json = response.json()

            decrypted_response = self.decrypt_response(
                response_json
            )

            _logger.info(
                'ICICI DECRYPTED RESPONSE: %s',
                decrypted_response
            )

            return {
                'status_code': response.status_code,
                'response': decrypted_response
            }

        except requests.exceptions.ConnectionError:

            raise ValidationError(
                'Unable to connect to ICICI server.'
            )


    def action_release_salary(self):

        if not self:
            raise ValidationError(
                'No payslips selected.'
            )
        for slip in self:
            if slip.icici_payment_status == 'paid':
                raise ValidationError(
                    f'Salary already released for {slip.employee_id.name}'
                )
            if slip.state in ['draft', 'cancel']:
                raise ValidationError(
                    f'{slip.employee_id.name} payslip is not confirmed.'
                )
            employee = slip.employee_id
            bank_account_rec = (
                employee.bank_account_ids.filtered(
                    lambda b: b.acc_number
                )[:1]
            )

            if not bank_account_rec:

                raise ValidationError(
                    f'Employee bank account missing for {employee.name}'
                )

            if not bank_account_rec.acc_number:

                raise ValidationError(
                    f'Employee account number missing for {employee.name}'
                )

            amount = 1
            # amount = int(slip.net_wage)

            if amount <= 0:

                raise ValidationError(
                    f'Invalid salary amount for {employee.name}'
                )

        unique_id = uuid.uuid4().hex[:16].upper()
        _logger.info(
                'unique_id: %s',
                unique_id
            )


        create_payload = {
            "AGGRID": "CIBBULK001",
            "AGGRNAME": "BULKTESTING",
            "CORPID": "TXBCORP1",
            "USERID": "USER1",
            "URN": "CIBTESTING",
            "UNIQUEID": unique_id
        }
        _logger.info(
            'create_payload : %s',
            create_payload
        )

        url = (
            'https://apibankingonesandbox.icici.bank.in'
            '/api/Corporate/CIB_SV/v1/Create'
        )

        self.env.cr.commit()

        result = self[0].call_icici_api(
            url,
            create_payload
        )

        response = result.get(
            'response'
        )

        try:

            json_start = response.find('{')

            json_end = response.rfind('}') + 1

            clean_response = response[
                json_start:json_end
            ]

            response_json = json.loads(
                clean_response
            )

        except Exception:

            raise ValidationError(
                f'Invalid ICICI response:\n\n{response}'
            )

        otp = (
            response_json.get('OTP')
            or response_json.get('otp')
            or response_json.get('AgOtp')
        )

        _logger.info(
            'ICICI OTP RECEIVED: %s',
            otp
        )

        if not otp:

            raise ValidationError(
                f'OTP not received.\n\n{response}'
            )

        self.write({
            'icici_generated_otp': otp,
            'icici_payment_status': 'otp_pending',
            'icici_reference': unique_id
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'icici.otp.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_payslip_ids': self.ids
            }
        }

    def process_bulk_payment(self, otp,payment_date):

        payment_date_obj = Date.to_date(payment_date)

        payment_date_str = payment_date_obj.strftime(
            "%d/%m/%Y"
        )
        _logger.info(
            "PAYMENT DATE = %s",
            payment_date_str
        )

        if not self:
            raise ValidationError('No payslips selected.')

        salary_file = (
            "FHR|3|06/05/2026|TESTING|10|INR|000451000301|0011^\r\n"
            "MDR|000451000301|0011|Krisala|10|INR|TestRemark|ICIC0000011|WIB^\r\n"
            "MCO|000405001257|0011|SteelHouse|5|INR|Steel|NFT|DLXB0000092^\r\n"
            "MCW|041101518240|0411|Beckam|5|INR|Beckam|ICIC0000011|WIB^\r\n"
        )

        _logger.info(
            'ICICI FINAL SALARY FILE:\n%s',
            salary_file
        )

        encoded_file = base64.b64encode(
            salary_file.encode()
        ).decode()

        _logger.info(
            'encoded_file:\n%s',
            encoded_file
        )

        payload = {
            "FILE_DESCRIPTION": "TESTING",
            "AGGR_ID": "CIBBULK001",
            "URN": "CIBTESTING",
            "AGGR_NAME": "BULKTESTING",
            "USER_ID": "USER1",
            "CORP_ID": "TXBCORP1",
            "UNIQUE_ID": self[0].icici_reference,
            "AGOTP": otp,
            "FILE_NAME": f"SALARY{random.randint(1000,9999)}.txt",
            "FILE_CONTENT": encoded_file
        }

        _logger.info(
            'payload:\n%s',
            payload
        )

        url = (
            'https://apibankingonesandbox.icici.bank.in'
            '/api/v1/cibbulkpayment_sv/bulkPayment'
        )

        result = self[0].call_icici_api(
            url,
            payload
        )

        _logger.info("ICICI RESULT: %s", result)

        response = result.get('response')

        if not response:
            raise ValidationError(
                'Empty response from ICICI.'
            )

        json_start = response.find('{')
        json_end = response.rfind('}') + 1

        clean_response = response[
            json_start:json_end
        ]

        response_json = json.loads(
            clean_response
        )

        _logger.info(
            'ICICI BULK PAYMENT RESPONSE: %s',
            response_json
        )

        file_seq_num = response_json.get(
            'FILE_SEQUENCE_NUM'
        )
        utr = response_json.get(
            'UTR'
        )

        if file_seq_num:

            for slip in self:
                slip.write({
                    'icici_payment_status': 'processing',
                    'icici_file_seq_num': file_seq_num,
                    'icici_utr': utr,
                    'icici_response': response,
                    'icici_generated_otp': False,
                })

            return True

        raise ValidationError(
            response_json.get('MESSAGE_DESC')
            or response_json.get('Message')
            or 'ICICI Payment Failed'
        )
    
    def action_reverse_payment(self,file_seq_num):

        if not file_seq_num:
            raise ValidationError(
                "File Sequence Number missing."
            )
        
        _logger.info(
            'file_seq_num: %s',
            file_seq_num
        )

        payload = {
            "AGGRID": "CIBBULK001",
            "CORPID": "TXBCORP1",
            "USERID": "TXBCORP1.USER1",
            "URN": "CIBTESTING",
            "FILESEQNUM": file_seq_num,
            "UNIQUEID": self.icici_reference,
            "ISENCRYPTED": "N"
        }
        _logger.info(
            'payload: %s',
            payload
        )

        result = self.call_icici_api(
            "https://apibankingonesandbox.icici.bank.in/api/v1/ReverseMis_sv",
            payload
        )

        response = result.get("response")

        if not response:
            raise ValidationError(
                "Empty response from ICICI."
            )

        response_json = json.loads(response)
        xml_data = response_json.get("XML", {})
        if xml_data.get("RESPONSE") != "SUCCESS":
            raise ValidationError(
                xml_data.get(
                    "MESSAGE",
                    "Reverse failed"
                )
            )
        _logger.info(
            "ICICI REVERSE RESPONSE: %s",
            response_json
        )
        self.write({
            'icici_payment_status': 'reversed',
            'icici_response': response,
            'icici_generated_otp': False,
            'icici_file_seq_num': False,
        })

        return True
    
    def action_open_reverse_wizard(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': 'Reverse Payment',
            'res_model': 'icici.reverse.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_payslip_id': self.id,
                'default_file_seq_num': self.icici_file_seq_num,
            }
        }