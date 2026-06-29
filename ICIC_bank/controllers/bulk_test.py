# from odoo import http
# from odoo.http import request

# import os
# import json
# import base64
# import random
# import string
# import logging
# import requests

# from Crypto.Cipher import AES, PKCS1_v1_5
# from Crypto.PublicKey import RSA
# from Crypto.Util.Padding import pad

# from cryptography import x509
# from cryptography.hazmat.primitives import serialization


# _logger = logging.getLogger(__name__)


# class ICICIBankController(http.Controller):

#     # COMMON RANDOM GENERATOR
#     def random_16(self):
#         return ''.join(
#             random.choices(string.digits, k=16)
#         )

#     # LOAD ICICI CERTIFICATE

#     def get_rsa_key(self):

#         module_path = os.path.dirname(
#             os.path.dirname(__file__)
#         )
#         cert_path = os.path.join(
#             module_path,
#             'icici_public.pem'
#         )

#         _logger.info("CERT PATH: %s", cert_path)

#         with open(cert_path, "rb") as f:
#             cert_data = f.read()

#         cert = x509.load_pem_x509_certificate(
#             cert_data
#         )

#         public_key = cert.public_key()

#         pem = public_key.public_bytes(
#             encoding=serialization.Encoding.PEM,
#             format=serialization.PublicFormat.SubjectPublicKeyInfo
#         )

#         rsa_key = RSA.import_key(pem)

#         return rsa_key

#     # COMMON ENCRYPTION METHOD

#     def encrypt_payload(self, payload):
#         rsa_key = self.get_rsa_key()
#         json_data = json.dumps(payload)
#         _logger.info("ORIGINAL PAYLOAD: %s", json_data)

#         # RANDOM AES KEY

#         randomno1 = self.random_16()

#         cipher_rsa = PKCS1_v1_5.new(rsa_key)

#         encrypted_key = cipher_rsa.encrypt(
#             randomno1.encode()
#         )

#         encr_key_b64 = base64.b64encode(
#             encrypted_key
#         ).decode()

#         # RANDOM IV

#         randomno2 = self.random_16()

#         data = randomno2 + json_data

#         cipher_aes = AES.new(
#             randomno1.encode(),
#             AES.MODE_CBC,
#             iv=randomno2.encode()
#         )

#         encrypted_data = cipher_aes.encrypt(
#             pad(data.encode(), AES.block_size)
#         )

#         encr_data_b64 = base64.b64encode(
#             encrypted_data
#         ).decode()

#         # FINAL REQUEST

#         request_payload = {
#             "requestId": "",
#             "service": "",
#             "encryptedKey": encr_key_b64,
#             "oaepHashingAlgorithm": "NONE",
#             "iv": "",
#             "encryptedData": encr_data_b64,
#             "clientInfo": "",
#             "optionalParam": ""
#         }

#         return request_payload

#     # COMMON API CALL METHOD

#     def call_icici_api(self, url, payload):

#         encrypted_payload = self.encrypt_payload(
#             payload
#         )

#         headers = {
#             "Content-Type": "application/json",
#             "Accept": "*/*",
#             "apikey": "HLAo88SpqGCpnwW87KcdwElPsfhPGVyG"
#         }

#         _logger.info("HITTING ICICI API")
#         _logger.info("URL: %s", url)

#         response = requests.post(
#             url,
#             headers=headers,
#             json=encrypted_payload,
#             timeout=60
#         )

#         _logger.info(
#             "STATUS CODE: %s",
#             response.status_code
#         )

#         _logger.info(
#             "RESPONSE TEXT: %s",
#             response.text
#         )

#         return {
#             "success": True,
#             "status_code": response.status_code,
#             "response": response.text
#         }

#     # API 1 : CREATE OTP

#     @http.route(
#         '/icici/create_otp',
#         type='json',
#         auth='public',
#         csrf=False,
#         methods=['POST']
#     )
#     def create_otp(self):

#         try:

#             payload = {
#                 "AGGRID": "CIBBULK001",
#                 "AGGRNAME": "BULKTESTING",
#                 "CORPID": "TXBCORP2",
#                 "USERID": "USER2",
#                 "URN": "CIBTESTING",
#                 "UNIQUEID": "11115"
#             }

#             url = (
#                 "https://apibankingonesandbox.icici.bank.in"
#                 "/api/Corporate/CIB_SV/v1/Create"
#             )

#             return self.call_icici_api(
#                 url,
#                 payload
#             )

#         except Exception as e:

#             _logger.exception(
#                 "CREATE OTP API ERROR"
#             )

#             return {
#                 "success": False,
#                 "error": str(e)
#             }

#     # API 2 : BULK PAYMENT

#     @http.route(
#         '/icici/bulk_payment',
#         type='json',
#         auth='public',
#         csrf=False,
#         methods=['POST']
#     )
#     def bulk_payment(self):

#         try:

#             sample_file = """
# FHR|7|05/07/2025|salsts312|33|INR|000451000301|0011^
# MDR|000451000301|0011|prachicib|33|INR|sals1t1|ICIC0000011|WIB^
# MCW|041101518240|0411|Munna|1|INR|Vendor|ICIC0000011|WIB^
#             """

#             encoded_file = base64.b64encode(
#                 sample_file.encode()
#             ).decode()

#             payload = {
#                 "FILE_DESCRIPTION": "TESTPAYROLL",
#                 "AGGR_ID": "CIBBULK001",
#                 "URN": "CIBTESTING",
#                 "AGGR_NAME": "BULKTESTING",
#                 "USER_ID": "USER2",
#                 "CORP_ID": "TXBCORP2",
#                 "UNIQUE_ID": "11115",
#                 "AGOTP": "123456",
#                 "FILE_NAME": "salary.txt",
#                 "FILE_CONTENT": encoded_file
#             }

#             url = (
#                 "https://apibankingonesandbox.icici.bank.in"
#                 "/api/v1/cibbulkpayment_sv/bulkPayment"
#             )

#             return self.call_icici_api(
#                 url,
#                 payload
#             )

#         except Exception as e:

#             _logger.exception(
#                 "BULK PAYMENT API ERROR"
#             )

#             return {
#                 "success": False,
#                 "error": str(e)
#             }

#     # API 3 : REVERSE STATUS

#     @http.route(
#         '/icici/reverse_status',
#         type='json',
#         auth='public',
#         csrf=False,
#         methods=['POST']
#     )
#     def reverse_status(self):

#         try:

#             payload = {
#                 "AGGRID": "CIBBULK001",
#                 "CORPID": "TXBCORP2",
#                 "USERID": "TXBCORP2.USER2",
#                 "URN": "CIBTESTING",
#                 "FILESEQNUM": "7958579",
#                 "ISENCRYPTED": "N"
#             }

#             url = (
#                 "https://apibankingonesandbox.icici.bank.in"
#                 "/api/v1/ReverseMis_sv"
#             )

#             return self.call_icici_api(
#                 url,
#                 payload
#             )

#         except Exception as e:

#             _logger.exception(
#                 "REVERSE STATUS API ERROR"
#             )

#             return {
#                 "success": False,
#                 "error": str(e)
#             }