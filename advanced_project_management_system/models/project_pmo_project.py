# -*- coding: utf-8 -*-
#############################################################################
#    Cybrosys Technologies Pvt. Ltd.
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    License LGPL-3.
#############################################################################
from odoo import _, api, fields, models

from .project_pmo_selection import (
    APPROVAL_STATES, HEALTH_STATUSES, ISSUE_CLOSED_STATES,
    MILESTONE_DONE_STATES, PMO_PRIORITIES, PROJECT_DONE_STATES,
    PROJECT_STATES, RISK_CLOSED_STATES, TASK_DONE_STATES, TEAM_ROLES,
)


class ProjectProjectPmo(models.Model):
    """PMO governance layer on top of ``project.project``.

    The core ``date_start`` and ``date`` fields are used as the planned start
    and planned end of the project (they are relabelled in the views), so the
    planning stays in one place and the Gantt and duration features keep
    working. Only the actual dates are added here.
    """
    _inherit = 'project.project'

    # ---- Identification ----
    project_code = fields.Char(
        string='Project ID', copy=False, readonly=True, default='New',
        index=True, help="Unique PMO reference of the project.")
    business_unit_id = fields.Many2one(
        'project.business.unit', string='Business Unit', tracking=True,
        help="Business unit the project is governed by.")
    department_id = fields.Many2one(
        'hr.department', string='Department', tracking=True,
        help="Department carrying out the project.")
    project_owner_id = fields.Many2one(
        'res.users', string='Project Owner', tracking=True,
        help="Executive accountable for the project.")
    project_coordinator_id = fields.Many2one(
        'res.users', string='Project Coordinator', tracking=True,
        help="User coordinating the day to day running of the project.")

    # ---- Planning ----
    actual_start_date = fields.Date(
        string='Actual Start Date', copy=False, tracking=True,
        help="Date the project actually started.")
    actual_end_date = fields.Date(
        string='Actual End Date', copy=False, tracking=True,
        help="Date the project actually ended.")
    schedule_variance_days = fields.Integer(
        string='Schedule Variance (Days)', compute='_compute_pmo_progress',
        store=True,
        help="Days between the planned end date and the actual end date, or "
             "today when the project is still running. A positive value means "
             "the project is late.")

    # ---- Governance ----
    pmo_state = fields.Selection(
        selection=PROJECT_STATES, string='Project Status', default='draft',
        required=True, tracking=True, group_expand='_group_expand_pmo_state',
        help="PMO lifecycle status of the project.")
    health_status = fields.Selection(
        selection=HEALTH_STATUSES, string='Health Status',
        compute='_compute_health_status', store=True, readonly=False,
        tracking=True,
        help="Green, Amber or Red. Computed from the schedule slippage, the "
             "open red risks and the critical issues, and can be overridden.")
    pmo_priority = fields.Selection(
        selection=PMO_PRIORITIES, string='Priority', default='medium',
        required=True, tracking=True, help="Priority of the project.")

    # ---- Progress roll-up ----
    progress_percentage = fields.Float(
        string='Overall Progress %', compute='_compute_pmo_progress',
        store=True, aggregator='avg',
        help="Share of completed tasks across the whole project.")
    total_milestone_count = fields.Integer(
        string='Total Milestones', compute='_compute_pmo_progress',
        store=True)
    completed_milestone_count = fields.Integer(
        string='Completed Milestones', compute='_compute_pmo_progress',
        store=True)
    total_task_count = fields.Integer(
        string='Total Tasks', compute='_compute_pmo_progress', store=True)
    completed_task_count = fields.Integer(
        string='Completed Tasks', compute='_compute_pmo_progress', store=True)
    open_issue_count = fields.Integer(
        string='Open Issues', compute='_compute_open_issue_risk_count',
        store=True)
    open_risk_count = fields.Integer(
        string='Open Risks', compute='_compute_open_issue_risk_count',
        store=True)
    red_risk_count = fields.Integer(
        string='Red Risks', compute='_compute_open_issue_risk_count',
        store=True)

    # ---- Approval ----
    approval_state = fields.Selection(
        selection=APPROVAL_STATES, string='Approval Status',
        default='not_required', required=True, tracking=True,
        help="Whether the project charter has been approved.")
    approved_by_id = fields.Many2one(
        'res.users', string='Approved By', readonly=True, copy=False,
        help="User who approved the project.")
    approval_date = fields.Datetime(
        string='Approval Date', readonly=True, copy=False,
        help="When the project was approved.")

    # ---- Relations ----
    team_member_ids = fields.One2many(
        'project.team.member', 'project_id', string='Team Allocation',
        help="Team allocation structure of the project.")
    risk_ids = fields.One2many('project.risk', 'project_id', string='Risks',
                               help="Risk register of the project.")
    issue_ids = fields.One2many('project.issue', 'project_id',
                                string='Issues',
                                help="Issue register of the project.")
    risk_count = fields.Integer(string='Risk Count',
                                compute='_compute_open_issue_risk_count',
                                store=True)

    # ---------------------------------------------------------
    # Compute methods
    # ---------------------------------------------------------

    @api.model
    def _group_expand_pmo_state(self, states, domain):
        """Always show every project status column in grouped views.

        :param states: the states currently present in the data.
        :param domain: the active domain.
        :return: the full list of status keys.
        """
        return [key for key, _label in PROJECT_STATES]

    @api.depends('task_ids.pmo_state', 'task_ids.active',
                 'milestone_ids.pmo_state', 'date', 'actual_end_date')
    def _compute_pmo_progress(self):
        """Roll the milestone and task counters up to the project."""
        today = fields.Date.context_today(self)
        for project in self:
            tasks = project.task_ids.filtered(lambda t: not t.parent_id)
            done_tasks = tasks.filtered(
                lambda t: t.pmo_state in TASK_DONE_STATES)
            milestones = project.milestone_ids
            done_milestones = milestones.filtered(
                lambda m: m.pmo_state in MILESTONE_DONE_STATES)

            project.total_task_count = len(tasks)
            project.completed_task_count = len(done_tasks)
            project.total_milestone_count = len(milestones)
            project.completed_milestone_count = len(done_milestones)
            project.progress_percentage = (
                round(100.0 * len(done_tasks) / len(tasks), 2)
                if tasks else 0.0)

            reference = project.actual_end_date or today
            project.schedule_variance_days = (
                (reference - project.date).days if project.date else 0)

    @api.depends('risk_ids.is_open', 'risk_ids.risk_rating',
                 'issue_ids.pmo_state')
    def _compute_open_issue_risk_count(self):
        """Count the open issues and risks weighing on the project."""
        for project in self:
            open_risks = project.risk_ids.filtered(lambda r: r.is_open)
            project.risk_count = len(project.risk_ids)
            project.open_risk_count = len(open_risks)
            project.red_risk_count = len(
                open_risks.filtered(lambda r: r.risk_rating == 'red'))
            project.open_issue_count = len(project.issue_ids.filtered(
                lambda i: i.pmo_state not in ISSUE_CLOSED_STATES))

    @api.depends('schedule_variance_days', 'red_risk_count', 'pmo_state',
                 'open_issue_count')
    def _compute_health_status(self):
        """Derive the RAG health from the slippage, the risks and the issues.

        The field stays editable, so a PMO can always override the automatic
        value on a given project.
        """
        for project in self:
            if project.pmo_state in PROJECT_DONE_STATES:
                project.health_status = 'green'
            elif (project.pmo_state in ('at_risk', 'delayed') or
                    project.red_risk_count or
                    project.schedule_variance_days > 7):
                project.health_status = 'red'
            elif (project.schedule_variance_days > 0 or
                    project.open_issue_count > 5 or
                    project.pmo_state == 'on_hold'):
                project.health_status = 'amber'
            else:
                project.health_status = 'green'

    # ---------------------------------------------------------
    # Overrides
    # ---------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """Assign the PMO project reference on creation.

        :param vals_list: list of value dictionaries.
        :return: the created recordset.
        """
        for vals in vals_list:
            if vals.get('project_code', 'New') == 'New':
                vals['project_code'] = self.env['ir.sequence'].next_by_code(
                    'project.project.pmo') or 'New'
        return super().create(vals_list)

    # ---------------------------------------------------------
    # Action methods
    # ---------------------------------------------------------

    def action_submit_for_approval(self):
        """Send the project charter for approval."""
        self.write({'approval_state': 'to_approve'})

    def action_approve(self):
        """Approve the project and stamp the approver."""
        self.write({
            'approval_state': 'approved',
            'approved_by_id': self.env.user.id,
            'approval_date': fields.Datetime.now(),
            'pmo_state': 'approved',
        })

    def action_reject_approval(self):
        """Reject the project charter."""
        self.write({'approval_state': 'rejected'})

    def action_view_risks(self):
        """Open the risk register of the project.

        :return: an act_window action dictionary.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Risks'),
            'res_model': 'project.risk',
            'view_mode': 'list,form,pivot,graph',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def action_view_team(self):
        """Open the team allocation of the project.

        :return: an act_window action dictionary.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Team Allocation'),
            'res_model': 'project.team.member',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def _get_team_users(self, roles):
        """Return the users allocated to this project with the given roles.

        :param roles: an iterable of role keys from ``TEAM_ROLES``.
        :return: a ``res.users`` recordset.
        """
        valid = {key for key, _label in TEAM_ROLES}
        roles = [role for role in roles if role in valid]
        members = self.team_member_ids.filtered(lambda m: m.role in roles)
        return members.mapped('user_id')

    @api.model
    def _cron_update_project_health(self):
        """Refresh the stored health of every running project.

        Meant to be called by the scheduled action so that a project turning
        Amber or Red overnight is reflected on the dashboards.
        """
        projects = self.search([('pmo_state', 'not in', PROJECT_DONE_STATES +
                                 ['cancelled'])])
        projects._compute_pmo_progress()
        projects._compute_open_issue_risk_count()
        projects._compute_health_status()
        return True
