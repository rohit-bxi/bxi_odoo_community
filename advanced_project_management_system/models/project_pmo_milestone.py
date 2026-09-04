# -*- coding: utf-8 -*-
#############################################################################
#    Cybrosys Technologies Pvt. Ltd.
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    License LGPL-3.
#############################################################################
from odoo import api, fields, models

from .project_pmo_selection import (
    HEALTH_STATUSES, MILESTONE_DONE_STATES, MILESTONE_STATES, PMO_PRIORITIES,
    TASK_DONE_STATES,
)


class ProjectMilestonePmo(models.Model):
    """PMO governance layer on top of ``project.milestone``.

    ``start_date`` and the core ``deadline`` act as the planned start and the
    planned end of the milestone, so only the actual dates and the target
    completion date are added here.
    """
    _inherit = 'project.milestone'

    milestone_code = fields.Char(
        string='Milestone ID', copy=False, readonly=True, default='New',
        index=True, help="Unique PMO reference of the milestone.")
    description = fields.Html(string='Milestone Description',
                              help="Full description of the milestone.")
    owner_id = fields.Many2one(
        'res.users', string='Milestone Owner', tracking=True,
        default=lambda self: self.env.user,
        help="User accountable for delivering this milestone.")
    actual_start_date = fields.Date(string='Actual Start Date', copy=False,
                                    tracking=True)
    actual_end_date = fields.Date(string='Actual End Date', copy=False,
                                  tracking=True)
    target_completion_date = fields.Date(
        string='Target Completion Date', tracking=True,
        help="Date the milestone is committed to be completed by.")
    pmo_state = fields.Selection(
        selection=MILESTONE_STATES, string='Status', default='not_started',
        required=True, tracking=True, group_expand='_group_expand_pmo_state',
        help="PMO lifecycle status of the milestone.")
    pmo_priority = fields.Selection(
        selection=PMO_PRIORITIES, string='Priority', default='medium',
        required=True, tracking=True)
    health_status = fields.Selection(
        selection=HEALTH_STATUSES, string='Health Status',
        compute='_compute_health_status', store=True, readonly=False,
        tracking=True,
        help="Green, Amber or Red, derived from the deadline and the status.")
    completion_percentage = fields.Float(
        string='Completion %', compute='_compute_milestone_progress',
        store=True, aggregator='avg',
        help="Share of completed tasks attached to this milestone.")
    total_task_count = fields.Integer(
        string='Total Tasks', compute='_compute_milestone_progress',
        store=True)
    completed_task_count = fields.Integer(
        string='Completed Tasks', compute='_compute_milestone_progress',
        store=True)
    acceptance_required = fields.Boolean(
        string='Acceptance Required', default=False, tracking=True,
        help="Tick when a formal sign-off is needed to accept the milestone.")
    approved_by_id = fields.Many2one('res.users', string='Approved By',
                                     readonly=True, copy=False)
    approval_date = fields.Datetime(string='Approval Date', readonly=True,
                                    copy=False)
    remarks = fields.Text(string='Remarks',
                          help="Free notes about this milestone.")
    risk_ids = fields.One2many('project.risk', 'milestone_id',
                               string='Risks')
    issue_ids = fields.One2many('project.issue', 'milestone_id',
                                string='Issues')
    is_overdue = fields.Boolean(string='Overdue',
                                compute='_compute_health_status', store=True,
                                help="Technical flag used by the dashboards.")
    company_id = fields.Many2one('res.company', string='Company',
                                 related='project_id.company_id', store=True)

    # ---------------------------------------------------------
    # Compute methods
    # ---------------------------------------------------------

    @api.model
    def _group_expand_pmo_state(self, states, domain):
        """Always show every milestone status column in grouped views.

        :param states: the states currently present in the data.
        :param domain: the active domain.
        :return: the full list of status keys.
        """
        return [key for key, _label in MILESTONE_STATES]

    @api.depends('task_ids.pmo_state')
    def _compute_milestone_progress(self):
        """Roll the task counters up to the milestone."""
        for milestone in self:
            tasks = milestone.task_ids.filtered(lambda t: not t.parent_id)
            done = tasks.filtered(lambda t: t.pmo_state in TASK_DONE_STATES)
            milestone.total_task_count = len(tasks)
            milestone.completed_task_count = len(done)
            milestone.completion_percentage = (
                round(100.0 * len(done) / len(tasks), 2) if tasks else 0.0)

    @api.depends('deadline', 'pmo_state', 'completion_percentage')
    def _compute_health_status(self):
        """Derive the RAG health and the overdue flag of the milestone."""
        today = fields.Date.context_today(self)
        for milestone in self:
            done = milestone.pmo_state in MILESTONE_DONE_STATES
            overdue = bool(milestone.deadline and milestone.deadline < today
                           and not done)
            milestone.is_overdue = overdue
            if done:
                milestone.health_status = 'green'
            elif overdue or milestone.pmo_state in ('delayed', 'blocked'):
                milestone.health_status = 'red'
            elif (milestone.deadline and
                  (milestone.deadline - today).days <= 7 and
                  milestone.completion_percentage < 80):
                milestone.health_status = 'amber'
            else:
                milestone.health_status = 'green'

    # ---------------------------------------------------------
    # Overrides
    # ---------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """Assign the PMO milestone reference on creation.

        :param vals_list: list of value dictionaries.
        :return: the created recordset.
        """
        for vals in vals_list:
            if vals.get('milestone_code', 'New') == 'New':
                vals['milestone_code'] = self.env['ir.sequence'].next_by_code(
                    'project.milestone.pmo') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        """Keep ``is_reached`` and the actual end date in sync with the status.

        :param vals: values being written.
        :return: True.
        """
        if 'pmo_state' in vals:
            if vals['pmo_state'] in MILESTONE_DONE_STATES:
                vals.setdefault('is_reached', True)
                vals.setdefault('actual_end_date',
                                fields.Date.context_today(self))
            elif vals['pmo_state'] != 'cancelled':
                vals.setdefault('is_reached', False)
        return super().write(vals)

    # ---------------------------------------------------------
    # Action methods
    # ---------------------------------------------------------

    def action_approve_milestone(self):
        """Accept the milestone and stamp the approver."""
        self.write({
            'pmo_state': 'accepted',
            'approved_by_id': self.env.user.id,
            'approval_date': fields.Datetime.now(),
        })
