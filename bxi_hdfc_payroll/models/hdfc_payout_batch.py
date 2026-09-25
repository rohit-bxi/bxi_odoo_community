# -*- coding: utf-8 -*-
import base64
import logging
import secrets
import time
from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, LockError, UserError
from odoo.fields import Command

from ..services import file_builder
from ..services.client_base import HdfcClientError, HdfcInvalidOtpError, HdfcUncertainError
from ..services.masking import to_log_text
from .hdfc_payout_line import TERMINAL_LINE_STATES

_logger = logging.getLogger(__name__)

MANAGER_GROUP = 'bxi_hdfc_payroll.group_hdfc_payout_manager'


class HdfcPayoutBatch(models.Model):
    _name = 'hdfc.payout.batch'
    _description = 'HDFC Payout Batch'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _check_company_auto = True

    name = fields.Char(required=True, readonly=True, copy=False, default='/')
    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    config_id = fields.Many2one('hdfc.bank.config', required=True, readonly=True, check_company=True)
    environment = fields.Selection(related='config_id.environment')
    payment_date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    line_ids = fields.One2many('hdfc.payout.line', 'batch_id', copy=False)
    payslip_ids = fields.Many2many('hr.payslip', compute='_compute_payslip_ids')
    payslip_count = fields.Integer(compute='_compute_payslip_ids')
    line_count = fields.Integer(compute='_compute_amounts', store=True)
    amount_total = fields.Monetary(compute='_compute_amounts', store=True)
    amount_paid = fields.Monetary(compute='_compute_amounts', store=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('otp_pending', 'OTP Pending'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('partially_done', 'Partially Done'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('reversed', 'Reversed'),
    ], default='draft', required=True, readonly=True, copy=False, index=True, tracking=True)

    bank_reference = fields.Char(readonly=True, copy=False, index=True)
    otp_reference = fields.Char(readonly=True, copy=False)
    otp_requested_at = fields.Datetime(readonly=True, copy=False)
    otp_expires_at = fields.Datetime(compute='_compute_otp_expires_at')
    otp_attempts = fields.Integer(readonly=True, copy=False)
    file_sequence_number = fields.Char(readonly=True, copy=False, index=True, tracking=True)
    file_attachment_id = fields.Many2one('ir.attachment', string='Bank File', readonly=True, copy=False)
    submitted_at = fields.Datetime(readonly=True, copy=False)
    last_sync_at = fields.Datetime(string='Last Status Sync', readonly=True, copy=False)
    reversal_reason = fields.Text(readonly=True, copy=False)
    move_ids = fields.Many2many('account.move', compute='_compute_move_ids')
    move_count = fields.Integer(compute='_compute_move_ids')
    log_ids = fields.One2many('hdfc.api.log', 'batch_id')
    log_count = fields.Integer(compute='_compute_log_count')

    _bank_reference_uniq = models.Constraint(
        'unique(bank_reference)',
        'The HDFC bank reference must be unique.',
    )

    # ------------------------------------------------------------
    # Compute / CRUD
    # ------------------------------------------------------------

    @api.depends('line_ids.payslip_id')
    def _compute_payslip_ids(self):
        for batch in self:
            batch.payslip_ids = batch.line_ids.payslip_id
            batch.payslip_count = len(batch.payslip_ids)

    @api.depends('line_ids.amount', 'line_ids.state')
    def _compute_amounts(self):
        for batch in self:
            batch.line_count = len(batch.line_ids)
            batch.amount_total = sum(batch.line_ids.mapped('amount'))
            batch.amount_paid = sum(batch.line_ids.filtered(lambda l: l.state == 'paid').mapped('amount'))

    @api.depends('otp_requested_at', 'config_id.otp_validity_minutes')
    def _compute_otp_expires_at(self):
        for batch in self:
            batch.otp_expires_at = batch.otp_requested_at and (
                batch.otp_requested_at + timedelta(minutes=batch.config_id.otp_validity_minutes)
            )

    @api.depends('line_ids.move_id', 'line_ids.reversal_move_id')
    def _compute_move_ids(self):
        for batch in self:
            batch.move_ids = batch.line_ids.move_id | batch.line_ids.reversal_move_id
            batch.move_count = len(batch.move_ids)

    def _compute_log_count(self):
        counts = dict(self.env['hdfc.api.log'].sudo()._read_group(
            [('batch_id', 'in', self.ids)], ['batch_id'], ['__count']))
        for batch in self:
            batch.log_count = counts.get(batch, 0)

    @api.model
    def _new_bank_reference(self):
        while True:
            reference = 'HP' + secrets.token_hex(5).upper()
            if not self.sudo().search_count([('bank_reference', '=', reference)], limit=1):
                return reference

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                company = self.env['res.company'].browse(vals.get('company_id')) or self.env.company
                vals['name'] = self.env['ir.sequence'].with_company(company).next_by_code('hdfc.payout.batch') or '/'
            vals.setdefault('bank_reference', self._new_bank_reference())
        batches = super().create(vals_list)
        for batch in batches:
            for index, line in enumerate(batch.line_ids.sorted('id'), start=1):
                line.line_reference = '%s%04d' % (batch.bank_reference, index)
        return batches

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft_or_cancelled(self):
        if any(batch.state not in ('draft', 'cancelled') for batch in self):
            raise UserError(_('Only draft or cancelled HDFC batches can be deleted.'))

    # ------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------

    def _check_manager(self):
        if not self.env.su and not self.env.user.has_group(MANAGER_GROUP):
            raise AccessError(_('Only HDFC payout managers can perform this operation.'))

    def _lock(self):
        try:
            self.lock_for_update(allow_referencing=True)
        except LockError as exc:
            raise UserError(_('This HDFC batch is being processed by another user. Please try again.')) from exc

    def _check_state(self, *states):
        for batch in self:
            if batch.state not in states:
                raise UserError(_(
                    'Batch %(batch)s is in state "%(state)s"; this action is not allowed.',
                    batch=batch.name,
                    state=dict(self._fields['state'].selection)[batch.state],
                ))

    def _is_otp_expired(self):
        self.ensure_one()
        return not self.otp_expires_at or fields.Datetime.now() > self.otp_expires_at

    # ------------------------------------------------------------
    # Bank calls
    # ------------------------------------------------------------

    def _call_bank(self, operation, method, *args, request=None):
        """Call the configured HDFC client and record a masked API log.

        Callers turn HdfcClientError into a notification instead of raising, so
        the log (and any state such as OTP attempts) is committed. Bank calls
        always happen before the batch is modified.
        """
        self.ensure_one()
        config = self.config_id
        client = config._get_client()
        started = time.monotonic()
        result = error = None
        try:
            result = getattr(client, method)(*args)
            return result
        except HdfcClientError as exc:
            error = exc
            raise
        except Exception as exc:
            error = exc
            _logger.exception('Unexpected HDFC client error (%s) on batch %s', operation, self.name)
            raise HdfcClientError(_('Unexpected error while communicating with HDFC.')) from exc
        finally:
            self.env['hdfc.api.log'].sudo().create({
                'batch_id': self.id,
                'config_id': config.id,
                'company_id': self.company_id.id,
                'operation': operation,
                'environment': config.environment,
                'success': error is None,
                'duration_ms': int((time.monotonic() - started) * 1000),
                'request_masked': to_log_text(request),
                'response_masked': to_log_text(result),
                'error': error and str(error) or False,
            })

    def action_request_otp(self):
        """Ask HDFC for an OTP (also used to resend) and open the OTP wizard."""
        self.ensure_one()
        self._check_manager()
        self._lock()
        self._check_state('draft', 'otp_pending')
        if not self.line_ids:
            raise UserError(_('The batch has no payout lines.'))
        if errors := self.config_id._get_setup_errors():
            raise UserError('\n'.join(errors))
        try:
            result = self._call_bank('otp', 'request_otp', self, request={
                'bank_reference': self.bank_reference,
                'line_count': self.line_count,
                'amount_total': self.amount_total,
            })
        except HdfcClientError as exc:
            return self._notify(_('HDFC OTP request failed: %s', exc), 'danger')
        self.write({
            'state': 'otp_pending',
            'otp_reference': result.get('otp_reference'),
            'otp_requested_at': fields.Datetime.now(),
            'otp_attempts': 0,
        })
        self.message_post(body=_('OTP requested from HDFC. %s', result.get('message') or ''))
        return self._action_open_otp_wizard(result.get('message'))

    def action_open_otp_wizard(self):
        self.ensure_one()
        self._check_manager()
        self._check_state('otp_pending')
        if self._is_otp_expired():
            raise UserError(_('The OTP has expired. Please request a new one.'))
        return self._action_open_otp_wizard()

    def _action_open_otp_wizard(self, message=None):
        return {
            'type': 'ir.actions.act_window',
            'name': _('HDFC OTP Verification'),
            'res_model': 'hdfc.otp.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_batch_id': self.id, 'default_message': message or False},
        }

    def _submit_with_otp(self, otp):
        """Build the bulk file and submit it with the OTP.

        :return: an action (notification on success, the OTP wizard again on a wrong OTP)
        """
        self.ensure_one()
        self._check_manager()
        self._lock()
        self._check_state('otp_pending')
        if self._is_otp_expired():
            self._reset_otp(_('OTP expired before submission.'))
            return self._notify(_('The OTP has expired. Request a new one.'), 'warning', reload=True)

        filename, content = file_builder.build(self)
        request = {
            'bank_reference': self.bank_reference,
            'otp_reference': self.otp_reference,
            'filename': filename,
            'line_count': self.line_count,
            'amount_total': self.amount_total,
        }
        try:
            result = self._call_bank('submit', 'submit_bulk', self, otp, filename, content, request=request)
        except HdfcInvalidOtpError:
            attempts = self.otp_attempts + 1
            if attempts >= self.config_id.otp_max_attempts:
                self._reset_otp(_('Maximum OTP attempts reached.'))
                return self._notify(_('Maximum OTP attempts reached. Request a new OTP.'), 'danger', reload=True)
            self.otp_attempts = attempts
            remaining = self.config_id.otp_max_attempts - attempts
            return self._action_open_otp_wizard(_('Invalid OTP. %s attempt(s) left.', remaining))
        except HdfcUncertainError as exc:
            # The bank may have accepted the file: never resubmit, let the status sync decide.
            self._mark_submitted(filename, content, file_sequence_number=False)
            self.message_post(body=_('Submission outcome unknown (%s). The status sync will reconcile this batch.', exc))
            return self._notify(_('HDFC did not confirm the submission. The status will be checked automatically.'),
                                'warning', reload=True)
        except HdfcClientError as exc:
            return self._notify(_('HDFC rejected the submission: %s', exc), 'danger', reload=True)

        self._mark_submitted(filename, content, result.get('file_sequence_number'))
        self.message_post(body=_('Bulk file submitted to HDFC. %s', result.get('message') or ''))
        return self._notify(_('Salary file submitted to HDFC.'), 'success', reload=True)

    def _mark_submitted(self, filename, content, file_sequence_number):
        attachment = self.env['ir.attachment'].sudo().create({
            'name': filename,
            'datas': base64.b64encode(content),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'text/csv',
        })
        self.write({
            'state': 'processing',
            'file_attachment_id': attachment.id,
            'file_sequence_number': file_sequence_number,
            'submitted_at': fields.Datetime.now(),
            'otp_reference': False,
            'otp_attempts': 0,
        })
        self.line_ids.filtered(lambda l: l.state == 'draft').state = 'submitted'

    def _reset_otp(self, reason):
        self.write({'state': 'draft', 'otp_reference': False, 'otp_requested_at': False, 'otp_attempts': 0})
        self.message_post(body=reason)

    def _notify(self, message, level, reload=False):
        action = {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'type': level, 'message': message, 'sticky': level != 'success'},
        }
        if reload:
            action['params']['next'] = {'type': 'ir.actions.client', 'tag': 'soft_reload'}
        return action

    # ------------------------------------------------------------
    # Status sync
    # ------------------------------------------------------------

    def action_refresh_status(self):
        self.ensure_one()
        self._check_manager()
        self._check_state('processing', 'done', 'partially_done')
        if error := self._sync_status():
            return self._notify(_('HDFC status check failed: %s', error), 'danger')
        return self._notify(_('Status refreshed.'), 'success', reload=True)

    def _sync_status(self):
        """Fetch line statuses from HDFC, update lines, post entries.

        :return: the bank error message, or None on success
        """
        self.ensure_one()
        self._lock()
        try:
            statuses = self._call_bank('status', 'get_status', self, request={
                'bank_reference': self.bank_reference,
                'file_sequence_number': self.file_sequence_number,
            })
        except HdfcClientError as exc:
            return str(exc)
        lines_by_ref = {line.line_reference: line for line in self.line_ids}
        newly_paid = self.env['hdfc.payout.line']
        newly_returned = self.env['hdfc.payout.line']
        for status in statuses or []:
            line = lines_by_ref.get(status.get('line_reference'))
            if not line:
                _logger.warning('HDFC status for unknown line %s on batch %s', status.get('line_reference'), self.name)
                continue
            new_state = status.get('status')
            if new_state == 'paid' and line.state in ('submitted', 'processing'):
                line.write({
                    'state': 'paid',
                    'utr': status.get('utr'),
                    'bank_txn_ref': status.get('bank_txn_ref'),
                    'value_date': status.get('value_date') or self.payment_date,
                    'failure_reason': False,
                })
                newly_paid |= line
            elif new_state == 'failed' and line.state in ('submitted', 'processing'):
                line.write({'state': 'failed', 'failure_reason': status.get('reason')})
            elif new_state == 'returned' and line.state == 'paid':
                line.write({'state': 'returned', 'failure_reason': status.get('reason')})
                newly_returned |= line
            elif new_state == 'processing' and line.state == 'submitted':
                line.state = 'processing'

        if newly_paid:
            self._post_payment_entries(newly_paid)
        if newly_returned:
            self._post_reversal_entries(newly_returned)
        self._update_state_from_lines()
        self.last_sync_at = fields.Datetime.now()
        return None

    def _update_state_from_lines(self):
        for batch in self:
            states = set(batch.line_ids.mapped('state'))
            if not states or not states <= set(TERMINAL_LINE_STATES):
                continue
            paid = 'paid' in states
            if states == {'paid'}:
                batch.state = 'done'
            elif paid:
                batch.state = 'partially_done'
            elif batch.state != 'reversed':
                batch.state = 'failed'

    @api.model
    def _cron_sync_status(self):
        for batch in self.search([('state', '=', 'processing')]):
            try:
                with self.env.cr.savepoint():
                    if error := batch._sync_status():
                        _logger.warning('HDFC status sync failed for batch %s: %s', batch.name, error)
            except Exception:
                _logger.exception('HDFC status sync failed for batch %s', batch.name)

    @api.model
    def _cron_expire_otp(self):
        for batch in self.search([('state', '=', 'otp_pending')]):
            if batch._is_otp_expired():
                batch._reset_otp(_('OTP expired.'))

    # ------------------------------------------------------------
    # Cancel / reverse
    # ------------------------------------------------------------

    def action_cancel(self):
        self._check_manager()
        self._check_state('draft', 'otp_pending')
        self.line_ids.state = 'cancelled'
        self.write({'state': 'cancelled', 'otp_reference': False, 'otp_requested_at': False})

    def action_open_reverse_wizard(self):
        self.ensure_one()
        self._check_manager()
        self._check_state('processing', 'done', 'partially_done')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reverse HDFC Payout'),
            'res_model': 'hdfc.reverse.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_batch_id': self.id},
        }

    def _reverse(self, reason):
        self.ensure_one()
        self._check_manager()
        self._lock()
        self._check_state('processing', 'done', 'partially_done')
        try:
            self._call_bank('reverse', 'reverse', self, reason, request={
                'bank_reference': self.bank_reference,
                'file_sequence_number': self.file_sequence_number,
                'reason': reason,
            })
        except HdfcClientError as exc:
            return self._notify(_('HDFC rejected the reversal: %s', exc), 'danger')
        paid_lines = self.line_ids.filtered(lambda l: l.state == 'paid')
        if paid_lines:
            self._post_reversal_entries(paid_lines)
        self.line_ids.filtered(lambda l: l.state in ('draft', 'submitted', 'processing', 'paid')).state = 'reversed'
        self.write({'state': 'reversed', 'reversal_reason': reason})
        self.message_post(body=_('Payout reversed. Reason: %s', reason))
        return self._notify(_('Payout reversed.'), 'success', reload=True)

    # ------------------------------------------------------------
    # Accounting
    # ------------------------------------------------------------

    def _post_payment_entries(self, lines):
        """One entry per value date: Dr salary account per employee / Cr outstanding payments."""
        self.ensure_one()
        config = self.config_id
        debit_account = config._get_salary_debit_account()
        credit_account = config.credit_account_id
        if not (config.journal_id and debit_account and credit_account):
            raise UserError(_('The accounting configuration of %s is incomplete.', config.display_name))
        for value_date, date_lines in lines.grouped(lambda l: l.value_date or self.payment_date).items():
            move = self._create_entry(date_lines, value_date, debit_account, credit_account, reverse=False)
            date_lines.move_id = move

    def _post_reversal_entries(self, lines):
        """Counter-entry for exactly these lines, on the accounts of their original entry."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        for move, move_lines in lines.filtered('move_id').grouped('move_id').items():
            debit_account = move.line_ids.filtered(lambda ml: ml.debit)[:1].account_id
            credit_account = move.line_ids.filtered(lambda ml: ml.credit)[:1].account_id
            reversal = self._create_entry(move_lines, today, debit_account, credit_account, reverse=True)
            move_lines.reversal_move_id = reversal

    def _create_entry(self, lines, date, debit_account, credit_account, reverse):
        config = self.config_id
        total = sum(lines.mapped('amount'))
        prefix = _('Reversal: ') if reverse else ''
        ref = '%s / %s' % (self.name, self.file_sequence_number or self.bank_reference)
        line_cmds = [
            Command.create({
                'account_id': debit_account.id,
                'partner_id': line.partner_id.id,
                'name': prefix + line._get_entry_label(),
                'debit': 0.0 if reverse else line.amount,
                'credit': line.amount if reverse else 0.0,
            })
            for line in lines
        ]
        line_cmds.append(Command.create({
            'account_id': credit_account.id,
            'name': prefix + _('HDFC salary payout %s', ref),
            'debit': total if reverse else 0.0,
            'credit': 0.0 if reverse else total,
        }))
        move = self.env['account.move'].sudo().with_company(self.company_id).create({
            'move_type': 'entry',
            'journal_id': config.journal_id.id,
            'date': date,
            'ref': prefix + ref,
            'company_id': self.company_id.id,
            'line_ids': line_cmds,
        })
        if config.auto_post:
            move.action_post()
        self.message_post(body=Markup('%s <a href="#" data-oe-model="account.move" data-oe-id="%s">%s</a>') % (
            _('Reversal entry created:') if reverse else _('Payment entry created:'), move.id, move.display_name))
        return move

    # ------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------

    def action_view_payslips(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Payslips'),
            'res_model': 'hr.payslip',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.payslip_ids.ids)],
        }

    def action_view_moves(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Entries'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.move_ids.ids)],
        }

    def action_view_logs(self):
        self.ensure_one()
        self._check_manager()
        return {
            'type': 'ir.actions.act_window',
            'name': _('API Logs'),
            'res_model': 'hdfc.api.log',
            'view_mode': 'list,form',
            'domain': [('batch_id', '=', self.id)],
        }

    def action_download_file(self):
        self.ensure_one()
        if not self.file_attachment_id:
            raise UserError(_('No bank file has been generated for this batch.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % self.file_attachment_id.id,
            'target': 'self',
        }
