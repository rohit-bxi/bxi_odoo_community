# -*- coding: utf-8 -*-
#############################################################################
#    Cybrosys Technologies Pvt. Ltd.
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    License LGPL-3.
#############################################################################
from odoo import _, api, fields, models

from .project_pmo_selection import (
    RISK_CLOSED_STATES, RISK_IMPACTS, RISK_IMPACT_SCORE, RISK_PROBABILITIES,
    RISK_PROBABILITY_SCORE, RISK_RATINGS, RISK_STATES,
)


class ProjectRisk(models.Model):
    """Risk register entry.

    A risk can be raised at project level or narrowed down to a milestone or
    a task, which is what gives the Project > Milestone > Task > Risk
    hierarchy of the governance model.
    """
    _name = 'project.risk'
    _description = 'Project Risk'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'risk_score desc, id desc'

    name = fields.Char(string='Reference', default='New', copy=False,
                       readonly=True, help="Risk register reference.")
    title = fields.Char(string='Risk Title', required=True, tracking=True,
                        help="Short description of the risk.")
    description = fields.Html(string='Description',
                              help="Full description of the risk.")
    project_id = fields.Many2one('project.project', string='Project',
                                 required=True, ondelete='cascade',
                                 index=True, tracking=True,
                                 help="Project exposed to this risk.")
    milestone_id = fields.Many2one(
        'project.milestone', string='Milestone',
        domain="[('project_id', '=', project_id)]", ondelete='set null',
        help="Milestone exposed to this risk, when applicable.")
    task_id = fields.Many2one(
        'project.task', string='Task',
        domain="[('project_id', '=', project_id)]", ondelete='set null',
        help="Task exposed to this risk, when applicable.")
    owner_id = fields.Many2one('res.users', string='Risk Owner',
                               default=lambda self: self.env.user,
                               tracking=True,
                               help="User accountable for this risk.")
    state = fields.Selection(selection=RISK_STATES, string='Status',
                             default='identified', required=True,
                             tracking=True, help="Risk lifecycle status.")
    probability = fields.Selection(
        selection=RISK_PROBABILITIES, string='Probability', default='medium',
        required=True, tracking=True,
        help="Likelihood of the risk materialising.")
    impact = fields.Selection(
        selection=RISK_IMPACTS, string='Impact', default='medium',
        required=True, tracking=True,
        help="Consequence should the risk materialise.")
    risk_score = fields.Integer(
        string='Risk Score', compute='_compute_risk_rating', store=True,
        help="Probability score multiplied by the impact score.")
    risk_rating = fields.Selection(
        selection=RISK_RATINGS, string='Risk Rating',
        compute='_compute_risk_rating', store=True, tracking=True,
        help="Green up to 5, Amber up to 11, Red above.")
    mitigation_plan = fields.Html(string='Mitigation Plan',
                                  help="Planned mitigation actions.")
    contingency_plan = fields.Html(string='Contingency Plan',
                                   help="Fallback should the risk trigger.")
    identified_date = fields.Date(string='Identified On',
                                  default=fields.Date.context_today,
                                  help="Date the risk was raised.")
    target_date = fields.Date(string='Target Closure Date',
                              help="Date the risk should be closed by.")
    closure_date = fields.Date(string='Closure Date', readonly=True,
                               copy=False,
                               help="Date the risk was actually closed.")
    closure_remarks = fields.Text(string='Closure Remarks',
                                  help="Why the risk was closed or accepted.")
    is_open = fields.Boolean(string='Open', compute='_compute_is_open',
                             store=True,
                             help="Technical flag used by the dashboards.")
    is_escalated = fields.Boolean(string='Escalated',
                                  compute='_compute_is_open', store=True,
                                  help="True while the risk is escalated.")
    company_id = fields.Many2one('res.company', string='Company',
                                 related='project_id.company_id', store=True)

    # ---------------------------------------------------------
    # Compute methods
    # ---------------------------------------------------------

    @api.depends('probability', 'impact')
    def _compute_risk_rating(self):
        """Derive the risk score and its Green / Amber / Red rating."""
        for risk in self:
            score = (RISK_PROBABILITY_SCORE.get(risk.probability, 0) *
                     RISK_IMPACT_SCORE.get(risk.impact, 0))
            risk.risk_score = score
            if score <= 5:
                risk.risk_rating = 'green'
            elif score <= 11:
                risk.risk_rating = 'amber'
            else:
                risk.risk_rating = 'red'

    @api.depends('state')
    def _compute_is_open(self):
        """Flag the risks that still weigh on the project."""
        for risk in self:
            risk.is_open = risk.state not in RISK_CLOSED_STATES
            risk.is_escalated = risk.state == 'escalated'

    # ---------------------------------------------------------
    # Onchange methods
    # ---------------------------------------------------------

    @api.onchange('project_id')
    def _onchange_project_id(self):
        """Drop the milestone and the task when the project changes."""
        for risk in self:
            if risk.milestone_id.project_id != risk.project_id:
                risk.milestone_id = False
            if risk.task_id.project_id != risk.project_id:
                risk.task_id = False

    @api.onchange('task_id')
    def _onchange_task_id(self):
        """Inherit the milestone of the selected task when there is one."""
        for risk in self:
            if risk.task_id.milestone_id:
                risk.milestone_id = risk.task_id.milestone_id

    # ---------------------------------------------------------
    # Overrides
    # ---------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """Assign the risk register sequence on creation.

        :param vals_list: list of value dictionaries.
        :return: the created recordset.
        """
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'project.risk') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        """Stamp or clear the closure date when the status changes.

        :param vals: values being written.
        :return: True.
        """
        if 'state' in vals:
            if vals['state'] in RISK_CLOSED_STATES:
                vals.setdefault('closure_date', fields.Date.context_today(self))
            else:
                vals['closure_date'] = False
        return super().write(vals)

    # ---------------------------------------------------------
    # Action methods
    # ---------------------------------------------------------

    def action_escalate(self):
        """Escalate the risk to the PMO."""
        self.write({'state': 'escalated'})

    def action_close(self):
        """Close the risk."""
        self.write({'state': 'closed'})

    def action_accept(self):
        """Accept the risk as it stands."""
        self.write({'state': 'accepted'})
