# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class AntitrustCase(models.Model):
    """Confidential compliance case (consequences of a violation), CPO only."""
    _name = 'antitrust.case'
    _description = 'Compliance Case'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True,
                       default=lambda self: self.env._('New'))
    employee_ids = fields.Many2many('hr.employee', string='Employees', required=True)
    source = fields.Selection(
        [('incident', 'Meeting Incident'), ('interaction', 'Competitor Interaction'),
         ('bid', 'Bid / RFP'), ('other', 'Other')],
        string='Source', default='other', required=True,
    )
    incident_id = fields.Many2one('antitrust.incident', string='Incident')
    interaction_id = fields.Many2one('antitrust.interaction', string='Interaction')
    summary = fields.Text(string='Summary', required=True)
    investigation = fields.Html(string='Investigation Notes')
    outcome = fields.Selection(
        [
            ('no_violation', 'No Violation'),
            ('advisory', 'Advisory'),
            ('training_required', 'Training Required'),
            ('disciplinary', 'Disciplinary Action'),
            ('legal_action', 'Legal Action'),
        ],
        string='Outcome', tracking=True,
    )
    actions_taken = fields.Text(string='Actions Taken')
    follow_up_date = fields.Date(string='Follow-up Date')
    closed_date = fields.Date(string='Closed On', readonly=True)
    state = fields.Selection([('open', 'Open'), ('closed', 'Closed')], default='open', required=True, tracking=True)
    attachment_ids = fields.Many2many('ir.attachment', 'antitrust_case_attachment_rel', 'case_id',
                                      'attachment_id', string='Confidential Documents')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', self.env._('New')) == self.env._('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('antitrust.case') or self.env._('New')
        return super().create(vals_list)

    def action_close(self):
        for rec in self:
            if not rec.outcome:
                raise UserError(self.env._("Set the outcome before closing the case."))
        self.write({'state': 'closed', 'closed_date': fields.Date.context_today(self)})

    def action_reopen(self):
        self.write({'state': 'open', 'closed_date': False})
