# -*- coding: utf-8 -*-
from odoo import models, fields
from odoo.exceptions import UserError


class AntitrustQuery(models.Model):
    """"In case of any doubt": a confidential question to the compliance team."""
    _name = 'antitrust.query'
    _description = 'Compliance Query'
    _inherit = ['antitrust.mixin']
    _order = 'id desc'
    _sequence_code = 'antitrust.query'
    _workflow_fields = {'state', 'name', 'employee_id', 'answer', 'answered_by_id', 'answered_date'}

    subject = fields.Char(string='Subject', required=True, tracking=True)
    situation = fields.Html(string='Situation', required=True)
    attachment_ids = fields.Many2many('ir.attachment', 'antitrust_query_attachment_rel', 'query_id',
                                      'attachment_id', string='Attachments')
    urgency = fields.Selection([('normal', 'Normal'), ('urgent', 'Urgent')], default='normal', required=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('submitted', 'Submitted'), ('answered', 'Answered'), ('closed', 'Closed')],
        string='Status', default='draft', required=True, tracking=True, copy=False,
    )
    answer = fields.Html(string='Answer')
    answered_by_id = fields.Many2one('res.users', string='Answered By', readonly=True)
    answered_date = fields.Datetime(string='Answered On', readonly=True)

    def action_submit(self):
        self._check_owner_or_cpo()
        for rec in self:
            if rec.state != 'draft':
                raise UserError(self.env._("Only draft queries can be submitted."))
            rec.sudo().state = 'submitted'
            rec._notify_cpo(
                self.env._("Compliance query %(ref)s: %(subject)s", ref=rec.name, subject=rec.subject),
                rec.situation,
                urgent=rec.urgency == 'urgent',
                email_contact=True,
            )

    def action_answer(self):
        if not self._is_cpo():
            raise UserError(self.env._("Only the compliance team can answer queries."))
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(self.env._("Only submitted queries can be answered."))
            if not rec.answer:
                raise UserError(self.env._("Write the answer first."))
            rec.sudo().write({'state': 'answered', 'answered_by_id': self.env.user.id,
                              'answered_date': fields.Datetime.now()})
            rec._done_cpo_activities(self.env._("Answered"))
            rec._notify_employee(self.env._("Your compliance query %(ref)s has been answered:", ref=rec.name)
                                 + rec.answer)

    def action_close(self):
        self._check_owner_or_cpo()
        for rec in self:
            if rec.state not in ('answered', 'submitted'):
                raise UserError(self.env._("Only submitted or answered queries can be closed."))
            if rec.state == 'submitted' and not self._is_cpo():
                raise UserError(self.env._("Wait for the answer before closing the query."))
            rec.sudo().state = 'closed'
