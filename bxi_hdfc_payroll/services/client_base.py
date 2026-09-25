# -*- coding: utf-8 -*-


class HdfcClientError(Exception):
    """The bank definitely rejected the request; nothing changed on HDFC's side."""


class HdfcInvalidOtpError(HdfcClientError):
    """The OTP was wrong or expired."""


class HdfcUncertainError(HdfcClientError):
    """The outcome is unknown (timeout, dropped connection after sending).

    Callers must not retry a submission on this error; the status sync
    reconciles the batch using its bank reference.
    """


class HdfcClientBase:
    """Interface every HDFC client implements.

    Line statuses returned by :meth:`get_status` use the payout line vocabulary:
    ``processing``, ``paid``, ``failed`` or ``returned``.
    """

    def __init__(self, config):
        self.config = config

    def test_connection(self):
        """:return: ``{'message': str}``"""
        raise NotImplementedError

    def request_otp(self, batch):
        """Ask HDFC to send an OTP to the authorised signatory.

        :return: ``{'otp_reference': str, 'message': str}``
        """
        raise NotImplementedError

    def submit_bulk(self, batch, otp, filename, content):
        """Submit the bulk payment file approved by ``otp``.

        :return: ``{'file_sequence_number': str, 'message': str}``
        """
        raise NotImplementedError

    def get_status(self, batch):
        """:return: list of ``{'line_reference', 'status', 'utr', 'bank_txn_ref', 'value_date', 'reason'}``"""
        raise NotImplementedError

    def reverse(self, batch, reason):
        """:return: ``{'message': str}``"""
        raise NotImplementedError
