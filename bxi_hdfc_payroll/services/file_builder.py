# -*- coding: utf-8 -*-
"""Bulk payment file for HDFC.

PROVISIONAL layout until the HDFC bulk file specification is received:
one CSV row per payout line, no header, CRLF line endings. Only this module
changes when the final format is known.
"""
import csv
import io
import re

TXN_CODES = {
    'internal': 'I',
    'neft': 'N',
    'rtgs': 'R',
    'imps': 'M',
}
NAME_MAX = 35
NARRATION_MAX = 30


def _clean(text, limit):
    text = re.sub(r'[^A-Za-z0-9 ]', ' ', text or '')
    return ' '.join(text.split())[:limit]


def build(batch):
    """:return: ``(filename, content_bytes)``"""
    config = batch.config_id
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator='\r\n')
    value_date = batch.payment_date.strftime('%d/%m/%Y')
    for line in batch.line_ids.sorted('id'):
        writer.writerow([
            TXN_CODES[line.txn_type],
            line.line_reference,
            line.account_number,
            '%.2f' % line.amount,
            _clean(line.beneficiary_name, NAME_MAX),
            line.ifsc,
            _clean(line.narration, NARRATION_MAX),
            value_date,
            config.debit_account_number,
        ])
    filename = '%s.csv' % batch.bank_reference
    return filename, buffer.getvalue().encode('utf-8')
