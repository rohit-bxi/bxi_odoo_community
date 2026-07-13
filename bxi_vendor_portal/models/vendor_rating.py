# -*- coding: utf-8 -*-
from odoo import models, fields, api


class VendorRating(models.Model):
    _name = 'bxi.vendor.rating'
    _description = 'Vendor Performance Rating'
    _order = 'period_end desc'

    vendor_id = fields.Many2one('bxi.vendor', string='Vendor', required=True, ondelete='cascade')
    period_start = fields.Date(string='Period From', required=True)
    period_end = fields.Date(string='Period To', required=True)
    period_type = fields.Selection([
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('half_yearly', 'Half Yearly'),
        ('annual', 'Annual'),
    ], string='Period Type', default='quarterly')

    # ── Scoring Dimensions ────────────────────────────────────────────────────
    otd_score = fields.Float(string='On-Time Delivery (%)', digits=(5, 1), default=0.0)
    quality_score = fields.Float(string='Quality / Rejection Rate (%)', digits=(5, 1), default=0.0)
    lead_time_score = fields.Float(string='Lead Time Adherence (%)', digits=(5, 1), default=0.0)
    compliance_score = fields.Float(string='Document Compliance (%)', digits=(5, 1), default=0.0)
    responsiveness_score = fields.Float(string='Responsiveness Score (%)', digits=(5, 1), default=0.0)

    # ── Computed ──────────────────────────────────────────────────────────────
    overall_score = fields.Float(
        string='Overall Score',
        compute='_compute_overall',
        store=True,
        digits=(5, 1),
    )
    rating_label = fields.Char(
        string='Rating Grade',
        compute='_compute_overall',
        store=True,
    )

    remarks = fields.Text(string='Evaluator Remarks')
    evaluated_by = fields.Many2one('res.users', string='Evaluated By', default=lambda self: self.env.user)

    @api.depends('otd_score', 'quality_score', 'lead_time_score', 'compliance_score', 'responsiveness_score')
    def _compute_overall(self):
        for rec in self:
            # Weighted scoring: OTD 30%, Quality 25%, Lead Time 20%, Compliance 15%, Responsiveness 10%
            score = (
                rec.otd_score * 0.30 +
                rec.quality_score * 0.25 +
                rec.lead_time_score * 0.20 +
                rec.compliance_score * 0.15 +
                rec.responsiveness_score * 0.10
            )
            rec.overall_score = round(score, 1)
            if score >= 90:
                rec.rating_label = 'A — Excellent'
            elif score >= 75:
                rec.rating_label = 'B — Good'
            elif score >= 60:
                rec.rating_label = 'C — Average'
            else:
                rec.rating_label = 'D — Below Standard'

    def name_get(self):
        result = []
        for rec in self:
            result.append((rec.id, f'{rec.vendor_id.name} — {rec.period_start} to {rec.period_end}'))
        return result
