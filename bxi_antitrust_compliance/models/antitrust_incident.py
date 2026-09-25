# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError

YES_NO = [('yes', 'Yes'), ('no', 'No')]

MEETING_TYPES = [
    ('trade_association', 'Trade Association'),
    ('industry_event', 'Industry Event / Conference'),
    ('customer', 'Customer'),
    ('supplier', 'Supplier'),
    ('partner', 'Partner'),
    ('competitor', 'Competitor'),
    ('other', 'Other'),
]


class AntitrustIncident(models.Model):
    """A prohibited topic came up in a meeting: what the employee did about it."""
    _name = 'antitrust.incident'
    _description = 'Antitrust Meeting Incident'
    _inherit = ['antitrust.mixin']
    _order = 'incident_date desc, id desc'
    _sequence_code = 'antitrust.incident'
    _workflow_fields = {'state', 'name', 'employee_id', 'outcome', 'review_notes', 'case_id'}

    incident_date = fields.Date(string='Meeting Date', required=True, default=fields.Date.context_today)
    meeting_title = fields.Char(string='Meeting', required=True)
    meeting_type = fields.Selection(MEETING_TYPES, string='Meeting Type', required=True, default='industry_event')
    other_parties = fields.Text(string='Organisations and People Present', required=True)
    topic_ids = fields.Many2many('antitrust.topic', string='Topics Raised')
    reservation_stated = fields.Selection(YES_NO, string='Did you officially state your reservation?')
    discussion_stopped = fields.Selection(YES_NO, string='Was the discussion stopped or resolved?')
    left_meeting = fields.Selection(YES_NO, string='Did you leave the meeting?')
    departure_recorded = fields.Selection(YES_NO, string='Was your departure noted for the record?')
    departure_record_note = fields.Char(string='How was it recorded?', help="E.g. minutes, email to the organiser.")
    explanation = fields.Text(string='Explanation',
                              help="Required when the discussion continued and you did not leave.")
    description = fields.Html(string='What Happened', required=True)
    attachment_ids = fields.Many2many('ir.attachment', 'antitrust_incident_attachment_rel', 'incident_id',
                                      'attachment_id', string='Evidence')
    interaction_id = fields.Many2one('antitrust.interaction', string='Declared Interaction', readonly=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('reported', 'Reported'), ('under_review', 'Under Review'), ('closed', 'Closed')],
        string='Status', default='draft', required=True, tracking=True, copy=False,
    )
    outcome = fields.Selection(
        [('no_action', 'No Action'), ('advisory', 'Advisory'), ('escalated_to_case', 'Escalated to Case')],
        string='Outcome', tracking=True,
    )
    review_notes = fields.Text(string='Review Notes')
    case_id = fields.Many2one('antitrust.case', string='Case', readonly=True)

    def _check_complete(self):
        for rec in self:
            missing = [label for field, label in (
                ('reservation_stated', self.env._("reservation stated")),
                ('discussion_stopped', self.env._("discussion stopped")),
                ('left_meeting', self.env._("left the meeting")),
            ) if not rec[field]]
            if missing:
                raise UserError(self.env._("Please answer: %(questions)s.", questions=', '.join(missing)))
            if rec.discussion_stopped == 'no' and rec.left_meeting == 'no' and not rec.explanation:
                raise UserError(self.env._(
                    "The discussion continued and you did not leave the meeting: please explain why."))
            if rec.left_meeting == 'yes' and not rec.departure_recorded:
                raise UserError(self.env._("Please say whether your departure was noted for the record."))

    def action_report(self):
        self._check_owner_or_cpo()
        for rec in self:
            if rec.state != 'draft':
                raise UserError(self.env._("This incident has already been reported."))
            rec._check_complete()
            rec.sudo().state = 'reported'
            rec._notify_cpo(
                self.env._("Antitrust incident %(ref)s: %(meeting)s", ref=rec.name, meeting=rec.meeting_title),
                rec.description,
                urgent=True,
                email_contact=True,
            )

    def action_start_review(self):
        if not self._is_cpo():
            raise UserError(self.env._("Only the compliance team can review incidents."))
        self.filtered(lambda r: r.state == 'reported').write({'state': 'under_review'})

    def action_close(self):
        if not self._is_cpo():
            raise UserError(self.env._("Only the compliance team can close incidents."))
        for rec in self:
            if rec.state not in ('reported', 'under_review'):
                raise UserError(self.env._("Only reported incidents can be closed."))
            if not rec.outcome:
                raise UserError(self.env._("Set the outcome before closing the incident."))
            if rec.outcome == 'escalated_to_case' and not rec.case_id:
                rec.case_id = self.env['antitrust.case'].create({
                    'employee_ids': [(6, 0, rec.employee_id.ids)],
                    'source': 'incident',
                    'incident_id': rec.id,
                    'interaction_id': rec.interaction_id.id,
                    'summary': f"{rec.name}: {rec.meeting_title}",
                })
            rec.state = 'closed'
            rec._done_cpo_activities(self.env._("Closed"))

    def action_view_case(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'antitrust.case', 'view_mode': 'form',
                'res_id': self.case_id.id}
