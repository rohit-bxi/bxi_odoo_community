# -*- coding: utf-8 -*-
from unittest.mock import patch

from Cryptodome.PublicKey import RSA

from odoo.tests.common import TransactionCase


class ICICICommon(TransactionCase):
    """Shared fixtures for the ICICI Bank integration tests.

    Two independent RSA key pairs stand in for the real ICICI/client key
    files so no test ever touches ``icici_public.pem`` or
    ``private_key.pem``:

    * ``icici_keypair`` plays the role of ICICI's key pair. Its public half
      is returned by the mocked ``get_icici_public_key`` and is what
      ``encrypt_payload`` encrypts outgoing requests with.
    * ``client_keypair`` plays the role of the client's own key pair. It is
      returned by the mocked ``get_private_key`` and is what
      ``decrypt_response`` uses to decrypt ICICI's replies.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.icici_keypair = RSA.generate(2048)
        cls.client_keypair = RSA.generate(2048)

    def setUp(self):
        super().setUp()

        payslip_model = type(self.env['hr.payslip'])

        # The real methods cache key material on the model class itself, so
        # make sure no state leaks in or out of this test.
        payslip_model._icici_public_key_cache = None
        payslip_model._private_key_cache = None
        self.addCleanup(
            setattr, payslip_model, '_icici_public_key_cache', None)
        self.addCleanup(
            setattr, payslip_model, '_private_key_cache', None)

        patcher_public = patch.object(
            payslip_model,
            'get_icici_public_key',
            return_value=self.icici_keypair.publickey(),
        )
        patcher_private = patch.object(
            payslip_model,
            'get_private_key',
            return_value=self.client_keypair,
        )
        self.mock_get_icici_public_key = patcher_public.start()
        self.mock_get_private_key = patcher_private.start()
        self.addCleanup(patcher_public.stop)
        self.addCleanup(patcher_private.stop)

    def _create_employee_with_bank(self, name, acc_number, ifsc):
        """Create an employee with one usable bank account."""
        partner = self.env['res.partner'].create({'name': name})
        bank = self.env['res.bank'].create({
            'name': 'Bank for %s' % name,
            'bic': ifsc,
        })
        bank_account = self.env['res.partner.bank'].create({
            'acc_number': acc_number,
            'bank_id': bank.id,
            'partner_id': partner.id,
        })
        employee = self.env['hr.employee'].create({'name': name})
        employee.bank_account_ids = [(4, bank_account.id)]
        return employee

    def _create_payslip(
        self, employee, net_wage=50000.0, state='done', **vals,
    ):
        """Create a payslip and force it into the requested test state.

        ``net_wage`` is computed from the payslip's "NET" salary rule
        line and ``state`` normally only reaches ``done`` by running the
        real payroll workflow (``compute_sheet`` + ``action_payslip_done``).
        This module's logic only cares about their final value, not how
        payroll arrived at it, so both are forced with a direct ``write``
        after creation.
        """
        slip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            **vals,
        })
        slip.write({'net_wage': net_wage, 'state': state})
        return slip
