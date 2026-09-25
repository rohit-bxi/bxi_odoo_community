# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import UserError

INTERACTION_TYPES = [
    ('trade_association', 'Trade Association Meeting'),
    ('industry_event', 'Industry Event / Conference'),
    ('competitor_meeting', 'Meeting with a Competitor'),
    ('joint_bid', 'Joint Bid / Teaming Agreement'),
    ('benchmarking', 'Benchmarking / Information Exchange'),
    ('other', 'Other'),
]
HIGH_RISK_TYPES = ('competitor_meeting', 'joint_bid', 'benchmarking')
REMIND_AFTER_DAYS = 2
ESCALATE_AFTER_DAYS = 7


class AntitrustInteraction(models.Model):
    """Declaration of an upcoming interaction with competitors, and what happened afterwards."""
    _name = 'antitrust.interaction'
    _description = 'Competitor Interaction Declaration'
    _inherit = ['antitrust.mixin']
    _order = 'event_date desc, id desc'
    _sequence_code = 'antitrust.interaction'
    _workflow_fields = {'state', 'name', 'employee_id', 'conditions', 'reject_reason', 'cpo_attendance',
                        'reviewed_by_id', 'post_declared_date', 'incident_id', 'post_reminded', 'post_escalated'}

    interaction_type = fields.Selection(INTERACTION_TYPES, string='Type', required=True, default='industry_event')
    event_date = fields.Date(string='Date', required=True)
    organisations = fields.Text(string='Organisations / Competitors Involved', required=True)
    purpose = fields.Text(string='Purpose', required=True)
    agenda = fields.Text(string='Agenda')
    attachment_ids = fields.Many2many('ir.attachment', 'antitrust_interaction_attachment_rel', 'interaction_id',
                                      'attachment_id', string='Agenda / Documents')
    risk_level = fields.Selection([('low', 'Low'), ('high', 'High')], compute='_compute_risk_level', store=True)
    commit_no_topics = fields.Boolean(
        string='I will not discuss or agree on any of the prohibited topics')
    commit_report = fields.Boolean(
        string='If such topics come up, I will state my reservation, leave the meeting and report it')
    manager_id = fields.Many2one(related='employee_id.parent_id', store=True, string='Manager')
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('cpo_review', 'CPO Review'),
            ('cleared', 'Cleared'),
            ('rejected', 'Not Allowed'),
            ('done', 'Completed'),
            ('incident', 'Incident Reported'),
        ],
        string='Status', default='draft', required=True, tracking=True, copy=False,
    )
    conditions = fields.Text(string='Conditions from the CPO')
    cpo_attendance = fields.Boolean(string='Legal / CPO to Attend')
    reject_reason = fields.Text(string='Reason Not Allowed')
    reviewed_by_id = fields.Many2one('res.users', string='Reviewed By', readonly=True)
    post_declared_date = fields.Date(string='Post-event Confirmation', readonly=True)
    incident_id = fields.Many2one('antitrust.incident', string='Incident', readonly=True)
    post_reminded = fields.Boolean(readonly=True)
    post_escalated = fields.Boolean(readonly=True)
    topics_html = fields.Html(compute='_compute_topics_html', sanitize=True)

    @api.depends('interaction_type')
    def _compute_risk_level(self):
        for rec in self:
            rec.risk_level = 'high' if rec.interaction_type in HIGH_RISK_TYPES else 'low'

    def _compute_topics_html(self):
        topics = self.env['antitrust.topic'].sudo().search([('category', '=', 'discussion')])
        html = '<ul>' + ''.join(f'<li>{t.name}</li>' for t in topics) + '</ul>'
        for rec in self:
            rec.topics_html = html

    def action_submit(self):
        self._check_owner_or_cpo()
        for rec in self:
            if rec.state != 'draft':
                raise UserError(self.env._("Only draft declarations can be submitted."))
            if not (rec.commit_no_topics and rec.commit_report):
                raise UserError(self.env._("Please confirm both commitments before submitting."))
            if rec.risk_level == 'high':
                rec.sudo().state = 'cpo_review'
                rec._notify_cpo(self.env._("Review competitor interaction %(ref)s", ref=rec.name), rec.purpose)
            else:
                rec.sudo().state = 'cleared'

    def action_clear(self):
        if not self._is_cpo():
            raise UserError(self.env._("Only the compliance team can clear interactions."))
        for rec in self:
            if rec.state != 'cpo_review':
                raise UserError(self.env._("Only interactions under review can be cleared."))
            rec.write({'state': 'cleared', 'reviewed_by_id': self.env.user.id})
            rec._done_cpo_activities(self.env._("Cleared"))
            body = self.env._("Your interaction %(ref)s has been cleared.", ref=rec.name)
            if rec.conditions:
                body += ' ' + self.env._("Conditions: %(conditions)s", conditions=rec.conditions)
            if rec.cpo_attendance:
                body += ' ' + self.env._("Legal / CPO will attend.")
            rec._notify_employee(body)

    def action_reject(self):
        if not self._is_cpo():
            raise UserError(self.env._("Only the compliance team can reject interactions."))
        for rec in self:
            if rec.state != 'cpo_review':
                raise UserError(self.env._("Only interactions under review can be rejected."))
            if not rec.reject_reason:
                raise UserError(self.env._("Enter the reason."))
            rec.write({'state': 'rejected', 'reviewed_by_id': self.env.user.id})
            rec._done_cpo_activities(self.env._("Not allowed"))
            rec._notify_employee(self.env._("Your interaction %(ref)s is not allowed: %(reason)s",
                                            ref=rec.name, reason=rec.reject_reason))

    def action_confirm_no_issue(self):
        """Post-event: no prohibited topic was discussed."""
        self._check_owner_or_cpo()
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.state != 'cleared':
                raise UserError(self.env._("Only cleared interactions can be confirmed."))
            if rec.event_date > today:
                raise UserError(self.env._("You can confirm once the interaction has taken place."))
            rec.sudo().write({'state': 'done', 'post_declared_date': today})

    def action_report_incident(self):
        """Post-event: a prohibited topic came up; open a pre-filled incident report."""
        self.ensure_one()
        self._check_owner_or_cpo()
        if self.state != 'cleared':
            raise UserError(self.env._("Only cleared interactions can report an incident."))
        incident = self.env['antitrust.incident'].sudo().create({
            'employee_id': self.employee_id.id,
            'incident_date': self.event_date,
            'meeting_title': dict(INTERACTION_TYPES)[self.interaction_type],
            'meeting_type': 'competitor' if self.interaction_type in HIGH_RISK_TYPES else 'industry_event',
            'other_parties': self.organisations,
            'description': self.purpose,
            'interaction_id': self.id,
        })
        self.sudo().write({'state': 'incident', 'incident_id': incident.id,
                           'post_declared_date': fields.Date.context_today(self)})
        return {'type': 'ir.actions.act_window', 'res_model': 'antitrust.incident', 'view_mode': 'form',
                'res_id': incident.id}

    @api.model
    def _cron_post_event_follow_up(self):
        today = fields.Date.context_today(self)
        pending = self.sudo().search([('state', '=', 'cleared'), ('event_date', '<', today)])
        for rec in pending:
            days = (today - rec.event_date).days
            if days >= ESCALATE_AFTER_DAYS and not rec.post_escalated:
                rec._notify_cpo(self.env._("No post-event confirmation for %(ref)s", ref=rec.name))
                rec.post_escalated = True
            elif days >= REMIND_AFTER_DAYS and not rec.post_reminded:
                rec._notify_employee(self.env._(
                    "Please confirm how the interaction %(ref)s went: no prohibited topic discussed, or report "
                    "an incident.", ref=rec.name))
                rec.post_reminded = True
