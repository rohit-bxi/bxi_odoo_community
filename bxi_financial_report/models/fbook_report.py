# -*- coding: utf-8 -*-
from odoo import models, fields, api

class FbookReport(models.Model):
    _name = 'fbook.report'
    _description = 'Fbook Report'
    _order = 'date desc, id desc'

    name = fields.Char(string='Report Name', required=True)
    date = fields.Date(string='Date', default=fields.Date.context_today, required=True)
    company_id = fields.Many2one(
        'res.company', 
        string='Company', 
        required=True, 
        default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(
        'res.currency', 
        string='Currency', 
        related='company_id.currency_id', 
        readonly=True
    )
    amount = fields.Monetary(string='Amount', currency_field='currency_id')
    description = fields.Text(string='Description')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancel', 'Cancelled')
    ], string='Status', default='draft', required=True)

    def action_post(self):
        self.write({'state': 'posted'})

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_cancel(self):
        self.write({'state': 'cancel'})
