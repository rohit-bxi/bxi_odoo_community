# -*- coding: utf-8 -*-
#############################################################################
#    Cybrosys Technologies Pvt. Ltd.
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    License LGPL-3.
#############################################################################
from odoo import _, api, fields, models

from .project_pmo_selection import (
    HEALTH_STATUSES, PMO_PRIORITIES, SEVERITIES, SUBTASK_STATES,
    TASK_BLOCKED_STATES, TASK_DONE_STATES, TASK_STATES, TEST_STATUSES,
)


class ProjectTaskPmo(models.Model):
    """PMO governance layer on top of ``project.task``.

    Sub-tasks are ordinary tasks carrying a ``parent_id`` in Odoo, so the
    sub-task field set of the specification is served by the same model. The
    status selection is narrowed to the sub-task list through the view, and
    ``_check_subtask_state`` guarantees a sub-task can never hold a status
    that is reserved for parent tasks.

    Estimated, actual and remaining hours reuse the core ``allocated_hours``,
    ``effective_hours`` and ``remaining_hours`` so the timesheets stay the
    single source of truth.
    """
    _inherit = 'project.task'

    task_code = fields.Char(
        string='Task ID', copy=False, readonly=True, default='New',
        index=True, help="Unique PMO reference of the task or sub-task.")
    category_id = fields.Many2one('project.category', string='Category',
                                  help="Functional category of the task.")
    team_id = fields.Many2one('project.team.member', string='Team',
                              domain="[('project_id', '=', project_id)]",
                              help="Team allocation line owning this task.")
    reviewer_id = fields.Many2one('res.users', string='Reviewer',
                                  tracking=True,
                                  help="User reviewing the delivered work.")
    responsible_manager_id = fields.Many2one(
        'res.users', string='Responsible Manager', tracking=True,
        help="Manager accountable for this task.")

    # ---- Planning ----
    actual_start_date = fields.Datetime(string='Actual Start Date',
                                        copy=False, tracking=True)
    actual_end_date = fields.Datetime(string='Actual End Date', copy=False,
                                      tracking=True)
    actual_completion_date = fields.Datetime(
        string='Actual Completion Date', copy=False, readonly=True,
        help="Stamped automatically when the status becomes Completed.")
    sla_due_date = fields.Datetime(
        string='SLA Due Date', tracking=True,
        help="Contractual date the task must be delivered by.")
    is_sla_breached = fields.Boolean(
        string='SLA Breached', compute='_compute_pmo_flags', store=True,
        help="True when the SLA due date passed before completion.")
    is_overdue = fields.Boolean(string='Overdue',
                                compute='_compute_pmo_flags', store=True)
    age_days = fields.Integer(
        string='Age (Days)', compute='_compute_pmo_flags', store=True,
        help="Days elapsed since the task was created, used by the ageing "
             "report.")

    # ---- Governance ----
    pmo_state = fields.Selection(
        selection=TASK_STATES, string='Status', default='backlog',
        required=True, tracking=True, group_expand='_group_expand_pmo_state',
        help="PMO lifecycle status of the task.")
    pmo_priority = fields.Selection(
        selection=PMO_PRIORITIES, string='PMO Priority', default='medium',
        required=True, tracking=True)
    severity = fields.Selection(selection=SEVERITIES, string='Severity',
                                default='minor', tracking=True)
    health_status = fields.Selection(
        selection=HEALTH_STATUSES, string='Health Status',
        compute='_compute_health_status', store=True, readonly=False)
    completion_percentage = fields.Float(
        string='Completion %', default=0.0, tracking=True, aggregator='avg',
        help="Manually reported progress of the task.")

    # ---- Dependencies and blockers ----
    blocked_by_id = fields.Many2one(
        'project.task', string='Blocked By',
        domain="[('project_id', '=', project_id), ('id', '!=', id)]",
        help="Task currently blocking this one.")
    blocker_reason = fields.Text(string='Blocker Reason',
                                 help="Why the task is blocked.")
    is_blocked = fields.Boolean(string='Blocked',
                                compute='_compute_pmo_flags', store=True)

    # ---- Quality ----
    acceptance_criteria = fields.Html(
        string='Acceptance Criteria',
        help="What has to be true for the task to be accepted.")
    test_required = fields.Boolean(string='Test Required', default=False)
    test_status = fields.Selection(selection=TEST_STATUSES,
                                   string='Test Status',
                                   default='not_applicable', tracking=True)
    closure_remarks = fields.Text(string='Closure Remarks',
                                  help="Notes recorded when closing.")

    # ---- Relations ----
    risk_ids = fields.One2many('project.risk', 'task_id', string='Risks')
    issue_ids = fields.One2many('project.issue', 'task_id', string='Issues')
    risk_count = fields.Integer(string='Risk Count',
                                compute='_compute_related_counts')
    issue_count = fields.Integer(string='Issue Count',
                                 compute='_compute_related_counts')

    # ---------------------------------------------------------
    # Compute methods
    # ---------------------------------------------------------

    @api.model
    def _group_expand_pmo_state(self, states, domain):
        """Always show every task status column in grouped views.

        :param states: the states currently present in the data.
        :param domain: the active domain.
        :return: the full list of status keys.
        """
        return [key for key, _label in TASK_STATES]

    @api.depends('date_deadline', 'sla_due_date', 'pmo_state', 'create_date',
                 'actual_completion_date', 'blocked_by_id')
    def _compute_pmo_flags(self):
        """Derive the overdue, blocked, SLA and ageing indicators."""
        now = fields.Datetime.now()
        today = fields.Date.context_today(self)
        for task in self:
            done = task.pmo_state in TASK_DONE_STATES
            reference = task.actual_completion_date or now
            task.is_overdue = bool(
                task.date_deadline and task.date_deadline < now and not done)
            task.is_sla_breached = bool(
                task.sla_due_date and task.sla_due_date < reference
                and not (done and task.actual_completion_date and
                         task.actual_completion_date <= task.sla_due_date))
            task.is_blocked = bool(
                task.pmo_state in TASK_BLOCKED_STATES or task.blocked_by_id)
            if task.create_date and not done:
                task.age_days = (today - task.create_date.date()).days
            elif task.create_date and task.actual_completion_date:
                task.age_days = (task.actual_completion_date.date() -
                                 task.create_date.date()).days
            else:
                task.age_days = 0

    @api.depends('is_overdue', 'is_blocked', 'is_sla_breached', 'pmo_state')
    def _compute_health_status(self):
        """Derive the RAG health of the task."""
        for task in self:
            if task.pmo_state in TASK_DONE_STATES:
                task.health_status = 'green'
            elif task.is_overdue or task.is_sla_breached or task.is_blocked:
                task.health_status = 'red'
            elif task.pmo_state == 'rework':
                task.health_status = 'amber'
            else:
                task.health_status = 'green'

    def _compute_related_counts(self):
        """Count the risks and the issues raised against the task."""
        for task in self:
            task.risk_count = len(task.risk_ids)
            task.issue_count = len(task.issue_ids)

    # ---------------------------------------------------------
    # Constraint methods
    # ---------------------------------------------------------

    @api.constrains('completion_percentage')
    def _check_completion_percentage(self):
        """Keep the reported completion between 0 and 100.

        :raises ValidationError: when the percentage is out of range.
        """
        from odoo.exceptions import ValidationError
        for task in self:
            if not 0 <= task.completion_percentage <= 100:
                raise ValidationError(_(
                    "The completion of \"%s\" must be between 0 and 100.",
                    task.display_name))

    @api.constrains('pmo_state', 'parent_id')
    def _check_subtask_state(self):
        """Restrict sub-tasks to the sub-task status list.

        :raises ValidationError: when a sub-task holds a parent-only status.
        """
        from odoo.exceptions import ValidationError
        allowed = {key for key, _label in SUBTASK_STATES}
        for task in self:
            if task.parent_id and task.pmo_state not in allowed:
                raise ValidationError(_(
                    "\"%(name)s\" is a sub-task, so its status must be one of:"
                    " %(states)s.",
                    name=task.display_name,
                    states=', '.join(
                        label for key, label in SUBTASK_STATES)))

    @api.constrains('blocked_by_id')
    def _check_blocked_by(self):
        """Prevent a task from blocking itself.

        :raises ValidationError: when a task is its own blocker.
        """
        from odoo.exceptions import ValidationError
        for task in self:
            if task.blocked_by_id and task.blocked_by_id == task:
                raise ValidationError(_("A task cannot block itself."))

    # ---------------------------------------------------------
    # Onchange methods
    # ---------------------------------------------------------

    @api.onchange('parent_id')
    def _onchange_parent_id_pmo_state(self):
        """Move a task onto the sub-task status list when it gets a parent."""
        allowed = {key for key, _label in SUBTASK_STATES}
        for task in self:
            if task.parent_id and task.pmo_state not in allowed:
                task.pmo_state = 'not_started'

    # ---------------------------------------------------------
    # Overrides
    # ---------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """Assign the PMO task reference and default sub-task status.

        :param vals_list: list of value dictionaries.
        :return: the created recordset.
        """
        allowed = {key for key, _label in SUBTASK_STATES}
        for vals in vals_list:
            if vals.get('task_code', 'New') == 'New':
                vals['task_code'] = self.env['ir.sequence'].next_by_code(
                    'project.task.pmo') or 'New'
            if vals.get('parent_id') and vals.get(
                    'pmo_state', 'backlog') not in allowed:
                vals['pmo_state'] = 'not_started'
        return super().create(vals_list)

    def write(self, vals):
        """Stamp the actual dates as the PMO status moves.

        :param vals: values being written.
        :return: True.
        """
        if 'pmo_state' in vals:
            state = vals['pmo_state']
            now = fields.Datetime.now()
            if state in TASK_DONE_STATES:
                vals.setdefault('actual_completion_date', now)
                vals.setdefault('actual_end_date', now)
                vals.setdefault('completion_percentage', 100.0)
            elif state == 'in_progress':
                for task in self:
                    if not task.actual_start_date:
                        task.actual_start_date = now
                vals['actual_completion_date'] = False
        return super().write(vals)

    # ---------------------------------------------------------
    # Action methods
    # ---------------------------------------------------------

    def action_view_task_risks(self):
        """Open the risks raised against this task.

        :return: an act_window action dictionary.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Risks'),
            'res_model': 'project.risk',
            'view_mode': 'list,form',
            'domain': [('task_id', '=', self.id)],
            'context': {'default_project_id': self.project_id.id,
                        'default_task_id': self.id},
        }

    def action_view_task_issues(self):
        """Open the issues raised against this task.

        :return: an act_window action dictionary.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Issues'),
            'res_model': 'project.issue',
            'view_mode': 'list,form',
            'domain': [('task_id', '=', self.id)],
            'context': {'default_project_id': self.project_id.id,
                        'default_task_id': self.id},
        }
