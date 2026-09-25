# -*- coding: utf-8 -*-
from odoo import fields
from odoo.tools.float_utils import float_round

from .client_base import HdfcClientBase, HdfcInvalidOtpError

MOCK_OTP = '123456'
# Lines whose amount ends in .99 are rejected by the mock bank, to exercise failure paths.
MOCK_FAILURE_PAISE = 99


class HdfcMockClient(HdfcClientBase):
    """Simulated HDFC used in development, tests and neutralized databases."""

    def test_connection(self):
        return {'message': 'Mock HDFC connection OK.'}

    def request_otp(self, batch):
        return {
            'otp_reference': 'MOCK-%s' % batch.bank_reference,
            'message': 'Mock OTP sent. Use %s.' % MOCK_OTP,
        }

    def submit_bulk(self, batch, otp, filename, content):
        if otp != MOCK_OTP:
            raise HdfcInvalidOtpError('Invalid OTP.')
        return {
            'file_sequence_number': str(90000000 + batch.id),
            'message': 'Mock file %s accepted (%d bytes).' % (filename, len(content)),
        }

    def get_status(self, batch):
        value_date = batch.payment_date or fields.Date.context_today(batch)
        result = []
        for line in batch.line_ids.filtered(lambda l: l.state in ('submitted', 'processing')):
            paise = round(float_round(line.amount, 2) * 100) % 100
            if paise == MOCK_FAILURE_PAISE:
                result.append({
                    'line_reference': line.line_reference,
                    'status': 'failed',
                    'reason': 'Mock: beneficiary account closed',
                })
            else:
                result.append({
                    'line_reference': line.line_reference,
                    'status': 'paid',
                    'utr': 'MOCKUTR%010d' % line.id,
                    'bank_txn_ref': 'MOCKTXN%010d' % line.id,
                    'value_date': value_date,
                })
        return result

    def reverse(self, batch, reason):
        return {'message': 'Mock reversal accepted.'}
