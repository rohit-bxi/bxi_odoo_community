# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class ReportingCategory(models.Model):
    _name = 'reporting.category'
    _description = 'Reporting Category'
    _order = 'sequence, name'

    name = fields.Char(string='Category Name', required=True, translate=True)
    category_type = fields.Selection([
        ('investment_made', 'Investments Made'),
        ('investment_received', 'Investments Received'),
    ], string='Category Type', required=True, default='investment_made', index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    sub_category_ids = fields.One2many(
        'reporting.sub.category',
        'category_id',
        string='Sub Categories'
    )
    sub_category_count = fields.Integer(
        string='Sub Categories Count',
        compute='_compute_sub_category_count'
    )
    active = fields.Boolean(string='Active', default=True)

    @api.depends('sub_category_ids')
    def _compute_sub_category_count(self):
        for rec in self:
            rec.sub_category_count = len(rec.sub_category_ids)

    def action_view_sub_categories(self):
        self.ensure_one()
        return {
            'name': _('Sub Categories: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'reporting.sub.category',
            'view_mode': 'list,form',
            'domain': [('category_id', '=', self.id)],
            'context': {'default_category_id': self.id},
        }


class ReportingSubCategory(models.Model):
    _name = 'reporting.sub.category'
    _description = 'Reporting Sub Category'
    _order = 'sequence, name'

    name = fields.Char(string='Sub Category Name', required=True, translate=True)
    category_id = fields.Many2one(
        'reporting.category',
        string='Reporting Category',
        required=True,
        ondelete='cascade',
        index=True
    )
    category_type = fields.Selection(
        related='category_id.category_type',
        string='Category Type',
        store=True,
        readonly=True
    )
    account_ids = fields.Many2many(
        'account.account',
        'reporting_sub_category_account_rel',
        'sub_category_id',
        'account_id',
        string='Chart of Accounts',
        help='Chart of Accounts mapped to this Sub Category'
    )
    sequence = fields.Integer(string='Sequence', default=10)
    account_count = fields.Integer(
        string='Accounts Count',
        compute='_compute_account_count'
    )
    active = fields.Boolean(string='Active', default=True)

    @api.depends('account_ids')
    def _compute_account_count(self):
        for rec in self:
            rec.account_count = len(rec.account_ids)
