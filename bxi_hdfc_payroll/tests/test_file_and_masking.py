# -*- coding: utf-8 -*-
import csv
import io
import json

from odoo.tests import tagged

from ..services import file_builder
from ..services.masking import mask_payload, to_log_text
from .common import HdfcPayrollCommon


@tagged('post_install', '-at_install')
class TestHdfcFileAndMasking(HdfcPayrollCommon):

    def test_bulk_file_rows(self):
        internal = self._create_employee('Ira K.', [('50100000000011', self.hdfc_bank, True)])
        other = self._create_employee("Jai O'Neil", [('30000000000012', self.sbi_bank, True)])
        batch = self._release(self._create_payslip(internal, 1234.5) | self._create_payslip(other, 250000))

        filename, content = file_builder.build(batch)
        self.assertEqual(filename, '%s.csv' % batch.bank_reference)
        self.assertIn(b'\r\n', content)
        rows = list(csv.reader(io.StringIO(content.decode())))
        self.assertEqual(len(rows), 2)
        by_account = {row[2]: row for row in rows}
        self.assertEqual(by_account['50100000000011'][0], 'I')
        self.assertEqual(by_account['50100000000011'][3], '1234.50')
        self.assertEqual(by_account['30000000000012'][0], 'R')
        self.assertEqual(by_account['30000000000012'][4], 'Jai O Neil')
        self.assertEqual(rows[0][7], '30/09/2026')
        self.assertEqual(rows[0][8], self.config.debit_account_number)
        self.assertEqual({row[1] for row in rows}, set(batch.line_ids.mapped('line_reference')))

    def test_masking(self):
        masked = mask_payload({
            'otp': '123456',
            'AGOTP': '654321',
            'account_number': '50100000000011',
            'nested': [{'client_secret': 'x', 'amount': 10}],
            'content': b'raw',
        })
        self.assertEqual(masked['otp'], '***')
        self.assertEqual(masked['AGOTP'], '***')
        self.assertEqual(masked['account_number'], '**********0011')
        self.assertEqual(masked['nested'][0]['client_secret'], '***')
        self.assertEqual(masked['nested'][0]['amount'], 10)
        text = to_log_text({'otp': '123456', 'account_number': '50100000000011'})
        self.assertNotIn('123456', text)
        self.assertNotIn('50100000000011', text)
        json.loads(text)
