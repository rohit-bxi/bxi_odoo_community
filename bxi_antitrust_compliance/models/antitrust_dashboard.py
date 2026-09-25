# -*- coding: utf-8 -*-
from odoo import models, fields, api


class AntitrustDashboard(models.TransientModel):
    """Compliance overview for the CPO."""
    _name = 'antitrust.dashboard'
    _description = 'Compliance Dashboard'

    ack_rate = fields.Float(string='Policies Acknowledged (%)', compute='_compute_counts')
    ack_overdue = fields.Integer(string='Overdue Acknowledgements', compute='_compute_counts')
    open_queries = fields.Integer(string='Open Queries', compute='_compute_counts')
    open_incidents = fields.Integer(string='Open Incidents', compute='_compute_counts')
    interactions_to_review = fields.Integer(string='Interactions to Review', compute='_compute_counts')
    interactions_without_confirmation = fields.Integer(string='Awaiting Post-event Confirmation',
                                                       compute='_compute_counts')
    rfp_without_declaration = fields.Integer(string='RFPs Without Valid Declaration', compute='_compute_counts')
    declarations_to_approve = fields.Integer(string='Bid Declarations to Approve', compute='_compute_counts')
    open_cases = fields.Integer(string='Open Cases', compute='_compute_counts')

    @api.depends_context('uid')
    def _compute_counts(self):
        env = self.env
        acks = env['hr.policy.acknowledgement'].sudo().search([('is_current_version', '=', True),
                                                               ('state', '!=', 'cancelled')])
        done = acks.filtered(lambda a: a.state in ('acknowledged', 'waived'))
        today = fields.Date.context_today(self)
        rfps = env['crm.lead'].sudo().search([('is_tender_rfp', '=', True), ('active', '=', True),
                                              ('stage_id.is_won', '=', False)])
        values = {
            'ack_rate': 100.0 * len(done) / len(acks) if acks else 0.0,
            'ack_overdue': len(acks.filtered(lambda a: a.state == 'overdue')),
            'open_queries': env['antitrust.query'].sudo().search_count([('state', '=', 'submitted')]),
            'open_incidents': env['antitrust.incident'].sudo().search_count(
                [('state', 'in', ('reported', 'under_review'))]),
            'interactions_to_review': env['antitrust.interaction'].sudo().search_count(
                [('state', '=', 'cpo_review')]),
            'interactions_without_confirmation': env['antitrust.interaction'].sudo().search_count(
                [('state', '=', 'cleared'), ('event_date', '<', today)]),
            'rfp_without_declaration': len(rfps.filtered(lambda l: l.bid_compliance_state in ('missing', 'outdated'))),
            'declarations_to_approve': env['antitrust.bid.declaration'].sudo().search_count(
                [('state', '=', 'to_approve')]),
            'open_cases': env['antitrust.case'].sudo().search_count([('state', '=', 'open')]),
        }
        for rec in self:
            rec.update(values)

    def _open(self, model, domain, name):
        return {'type': 'ir.actions.act_window', 'name': name, 'res_model': model,
                'view_mode': 'list,form', 'domain': domain}

    def action_open_overdue(self):
        return self._open('hr.policy.acknowledgement', [('state', '=', 'overdue')], self.env._('Overdue'))

    def action_open_queries(self):
        return self._open('antitrust.query', [('state', '=', 'submitted')], self.env._('Open Queries'))

    def action_open_incidents(self):
        return self._open('antitrust.incident', [('state', 'in', ('reported', 'under_review'))],
                          self.env._('Open Incidents'))

    def action_open_interactions(self):
        return self._open('antitrust.interaction', [('state', '=', 'cpo_review')],
                          self.env._('Interactions to Review'))

    def action_open_unconfirmed(self):
        return self._open('antitrust.interaction', [('state', '=', 'cleared'),
                                                    ('event_date', '<', fields.Date.context_today(self))],
                          self.env._('Awaiting Confirmation'))

    def action_open_rfps(self):
        rfps = self.env['crm.lead'].search([('is_tender_rfp', '=', True), ('stage_id.is_won', '=', False)])
        ids = rfps.filtered(lambda l: l.bid_compliance_state in ('missing', 'outdated')).ids
        return self._open('crm.lead', [('id', 'in', ids)], self.env._('RFPs Without Declaration'))

    def action_open_declarations(self):
        return self._open('antitrust.bid.declaration', [('state', '=', 'to_approve')],
                          self.env._('Declarations to Approve'))

    def action_open_cases(self):
        return self._open('antitrust.case', [('state', '=', 'open')], self.env._('Open Cases'))
