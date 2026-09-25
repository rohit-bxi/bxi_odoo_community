# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models


class HdfcApiLog(models.Model):
    _name = 'hdfc.api.log'
    _description = 'HDFC API Log'
    _order = 'id desc'

    batch_id = fields.Many2one('hdfc.payout.batch', index=True, ondelete='cascade')
    config_id = fields.Many2one('hdfc.bank.config', ondelete='set null')
    company_id = fields.Many2one('res.company', required=True, index=True)
    operation = fields.Selection([
        ('test', 'Test Connection'),
        ('otp', 'Request OTP'),
        ('submit', 'Submit Bulk File'),
        ('status', 'Status Sync'),
        ('reverse', 'Reverse'),
    ], required=True)
    environment = fields.Char()
    success = fields.Boolean()
    duration_ms = fields.Integer(string='Duration (ms)')
    request_masked = fields.Text(string='Request')
    response_masked = fields.Text(string='Response')
    error = fields.Text()

    @api.model
    def _cron_cleanup(self):
        configs = self.env['hdfc.bank.config'].sudo().with_context(active_test=False).search([])
        for company, company_configs in configs.grouped('company_id').items():
            days = max(company_configs.mapped('log_retention_days') or [180])
            limit = fields.Datetime.now() - timedelta(days=days)
            self.sudo().search([('company_id', '=', company.id), ('create_date', '<', limit)]).unlink()
