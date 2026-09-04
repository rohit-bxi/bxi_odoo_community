# -*- coding: utf-8 -*-
##############################################################################
#    Cybrosys Technologies Pvt. Ltd.
#    Copyright (C) 2025-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    License AGPL-3.
##############################################################################
"""Role based PMO dashboards (CXO, PMO, Manager, User)."""
from odoo import http
from odoo.http import request

from odoo.addons.advanced_project_management_system.models.\
    project_pmo_selection import (
        MILESTONE_DONE_STATES, PROJECT_DONE_STATES,
        PROJECT_STATES, RISK_IMPACTS, RISK_PROBABILITIES, TASK_DONE_STATES,
    )

CXO_GROUP = 'advanced_project_management_system.group_apms_cxo'
PMO_GROUP = 'advanced_project_management_system.group_apms_pmo'
ADMIN_GROUP = 'advanced_project_management_system.group_apms_admin'
MANAGER_GROUP = 'advanced_project_management_system.group_apms_manager'
PROJECT_MANAGER_GROUP = 'project.group_project_manager'

OPEN_PROJECT_STATES = [key for key, _l in PROJECT_STATES
                       if key not in PROJECT_DONE_STATES + ['cancelled']]


class ProjectPmoDashboard(http.Controller):
    """Serves the four role based dashboards described by the PMO model.

    Every query runs through the connected user's own environment, so the
    access level record rules decide what each role actually sees. The role
    only decides *which widgets* are rendered, never whether the data is
    filtered.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _available_roles():
        """Return the dashboard roles the connected user may open.

        :return: a list of role keys, broadest first.
        """
        user = request.env.user
        roles = ['user']
        if user.has_group(MANAGER_GROUP) or user.has_group(
                PROJECT_MANAGER_GROUP):
            roles.append('manager')
        if user.has_group(PMO_GROUP) or user.has_group(ADMIN_GROUP):
            roles.append('pmo')
        if user.has_group(CXO_GROUP):
            roles.append('cxo')
        return roles

    @staticmethod
    def _visible_projects():
        """Return the projects the connected user may read.

        :return: a ``project.project`` recordset.
        """
        return request.env['project.project'].search([])

    @staticmethod
    def _action(name, model, domain, view_mode='list,form'):
        """Build the descriptor the client uses to open a drill-down.

        :param name: the action title.
        :param model: the technical model name.
        :param domain: the domain to apply.
        :param view_mode: comma separated view modes.
        :return: a dictionary.
        """
        return {'name': name, 'model': model, 'domain': domain,
                'view_mode': view_mode}

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @http.route('/project/pmo/roles', auth='user', type='jsonrpc')
    def get_roles(self):
        """Return the roles available to the user and the default one.

        :return: a dictionary with ``roles`` and ``default_role``.
        """
        roles = self._available_roles()
        return {'roles': roles, 'default_role': roles[-1]}

    @http.route('/project/pmo/cxo', auth='user', type='jsonrpc')
    def cxo_dashboard(self):
        """Portfolio health, projects by status, strategic milestones, risk
        heatmap, resource capacity and delayed projects.

        :return: a dictionary of widget payloads.
        """
        projects = self._visible_projects()
        risks = request.env['project.risk'].search(
            [('project_id', 'in', projects.ids), ('is_open', '=', True)])

        health = {'green': 0, 'amber': 0, 'red': 0}
        for project in projects:
            if project.health_status in health:
                health[project.health_status] += 1

        by_status = []
        for key, label in PROJECT_STATES:
            count = len(projects.filtered(lambda p, k=key: p.pmo_state == k))
            if count:
                by_status.append({'key': key, 'label': label,
                                  'count': count})

        strategic = request.env['project.milestone'].search(
            [('project_id', 'in', projects.ids),
             ('pmo_priority', 'in', ['high', 'critical']),
             ('pmo_state', 'not in', MILESTONE_DONE_STATES + ['cancelled'])],
            order='deadline asc', limit=15)

        impacts = [key for key, _l in RISK_IMPACTS]
        heatmap = []
        for prob_key, prob_label in RISK_PROBABILITIES:
            row = {'probability': prob_label, 'cells': []}
            for impact_key in impacts:
                matching = risks.filtered(
                    lambda r, p=prob_key, i=impact_key:
                    r.probability == p and r.impact == i)
                row['cells'].append({
                    'impact': impact_key,
                    'count': len(matching),
                    'ids': matching.ids,
                    'rating': matching[:1].risk_rating if matching else 'green',
                })
            heatmap.append(row)

        capacity = []
        allocations = request.env['project.team.member'].search(
            [('project_id', 'in', projects.ids)])
        per_user = {}
        for member in allocations:
            per_user.setdefault(member.user_id, 0.0)
            per_user[member.user_id] += member.allocation_percentage
        for user, total in sorted(per_user.items(), key=lambda kv: -kv[1])[:12]:
            capacity.append({'name': user.name, 'allocation': round(total, 1),
                             'overloaded': total > 100})

        delayed = projects.filtered(
            lambda p: p.schedule_variance_days > 0 and
            p.pmo_state in OPEN_PROJECT_STATES)

        return {
            'role': 'cxo',
            'health': health,
            'health_ids': {
                key: projects.filtered(
                    lambda p, k=key: p.health_status == k).ids
                for key in health},
            'projects_by_status': by_status,
            'strategic_milestones': [{
                'id': m.id, 'name': m.display_name,
                'project': m.project_id.display_name,
                'deadline': str(m.deadline or ''),
                'completion': m.completion_percentage,
                'health': m.health_status,
            } for m in strategic],
            'risk_heatmap': heatmap,
            'risk_impacts': [label for _k, label in RISK_IMPACTS],
            'resource_capacity': capacity,
            'delayed_projects': [{
                'id': p.id, 'name': p.display_name,
                'variance': p.schedule_variance_days,
                'health': p.health_status,
            } for p in delayed],
            'delayed_ids': delayed.ids,
        }

    @http.route('/project/pmo/pmo', auth='user', type='jsonrpc')
    def pmo_dashboard(self):
        """Project health, schedule variance, milestone completion, risk and
        issue tracking, cross project dependencies and resource utilization.

        :return: a dictionary of widget payloads.
        """
        projects = self._visible_projects()
        milestones = request.env['project.milestone'].search(
            [('project_id', 'in', projects.ids)])
        risks = request.env['project.risk'].search(
            [('project_id', 'in', projects.ids), ('is_open', '=', True)])
        issues = request.env['project.issue'].search(
            [('project_id', 'in', projects.ids), ('is_open', '=', True)])
        timesheets = request.env['account.analytic.line'].search(
            [('project_id', 'in', projects.ids)])

        dependencies = request.env['project.task'].search(
            [('project_id', 'in', projects.ids),
             ('blocked_by_id', '!=', False)])
        cross = [{
            'id': t.id, 'name': t.display_name,
            'project': t.project_id.display_name,
            'blocked_by': t.blocked_by_id.display_name,
            'blocker_project': t.blocked_by_id.project_id.display_name,
            'cross_project': t.project_id != t.blocked_by_id.project_id,
        } for t in dependencies]

        utilization = {}
        for line in timesheets:
            utilization.setdefault(line.user_id.name or '', 0.0)
            utilization[line.user_id.name or ''] += line.unit_amount

        return {
            'role': 'pmo',
            'project_health': [{
                'id': p.id, 'name': p.display_name,
                'health': p.health_status,
                'progress': p.progress_percentage,
                'variance': p.schedule_variance_days,
                'open_risks': p.open_risk_count,
                'open_issues': p.open_issue_count,
            } for p in projects],
            'milestone_completion': [{
                'id': m.id, 'name': m.display_name,
                'project': m.project_id.display_name,
                'completion': m.completion_percentage,
                'overdue': m.is_overdue,
            } for m in milestones],
            'risk_summary': {
                'red': len(risks.filtered(lambda r: r.risk_rating == 'red')),
                'amber': len(risks.filtered(
                    lambda r: r.risk_rating == 'amber')),
                'green': len(risks.filtered(
                    lambda r: r.risk_rating == 'green')),
                'escalated': len(risks.filtered(lambda r: r.is_escalated)),
            },
            'risk_ids': risks.ids,
            'issue_summary': {
                'total': len(issues),
                'escalated': len(issues.filtered(lambda i: i.is_escalated)),
                'critical': len(issues.filtered(
                    lambda i: i.pmo_priority == 'critical')),
                'showstopper': len(issues.filtered(
                    lambda i: i.severity == 'showstopper')),
            },
            'issue_ids': issues.ids,
            'cross_dependencies': cross,
            'resource_utilization': [
                {'name': name, 'hours': round(hours, 2)}
                for name, hours in sorted(utilization.items(),
                                          key=lambda kv: -kv[1])[:12]],
        }

    @http.route('/project/pmo/manager', auth='user', type='jsonrpc')
    def manager_dashboard(self):
        """Team utilization, task progress, overdue tasks, blocked tasks,
        open risks and open issues.

        :return: a dictionary of widget payloads.
        """
        projects = self._visible_projects()
        tasks = request.env['project.task'].search(
            [('project_id', 'in', projects.ids)])
        open_tasks = tasks.filtered(
            lambda t: t.pmo_state not in TASK_DONE_STATES + ['cancelled'])
        overdue = open_tasks.filtered(lambda t: t.is_overdue)
        blocked = open_tasks.filtered(lambda t: t.is_blocked)
        risks = request.env['project.risk'].search(
            [('project_id', 'in', projects.ids), ('is_open', '=', True)])
        issues = request.env['project.issue'].search(
            [('project_id', 'in', projects.ids), ('is_open', '=', True)])

        team = {}
        for task in open_tasks:
            for user in task.user_ids:
                entry = team.setdefault(
                    user.name, {'name': user.name, 'open': 0, 'overdue': 0,
                                'hours': 0.0})
                entry['open'] += 1
                if task.is_overdue:
                    entry['overdue'] += 1
                entry['hours'] += task.allocated_hours

        return {
            'role': 'manager',
            'team_utilization': sorted(team.values(),
                                       key=lambda e: -e['open'])[:15],
            'task_progress': {
                'total': len(tasks),
                'done': len(tasks.filtered(
                    lambda t: t.pmo_state in TASK_DONE_STATES)),
                'in_progress': len(tasks.filtered(
                    lambda t: t.pmo_state == 'in_progress')),
                'backlog': len(tasks.filtered(
                    lambda t: t.pmo_state == 'backlog')),
            },
            'overdue_tasks': [{
                'id': t.id, 'name': t.display_name,
                'project': t.project_id.display_name,
                'deadline': str(t.date_deadline or ''),
                'assignees': ', '.join(t.user_ids.mapped('name')),
            } for t in overdue[:25]],
            'overdue_ids': overdue.ids,
            'blocked_tasks': [{
                'id': t.id, 'name': t.display_name,
                'project': t.project_id.display_name,
                'reason': t.blocker_reason or (
                    t.blocked_by_id.display_name or ''),
            } for t in blocked[:25]],
            'blocked_ids': blocked.ids,
            'open_risk_count': len(risks),
            'open_risk_ids': risks.ids,
            'open_issue_count': len(issues),
            'open_issue_ids': issues.ids,
        }

    @http.route('/project/pmo/user', auth='user', type='jsonrpc')
    def user_dashboard(self):
        """My tasks, my sub-tasks, pending reviews, upcoming due dates,
        logged hours and personal progress.

        :return: a dictionary of widget payloads.
        """
        user = request.env.user
        Task = request.env['project.task']
        mine = Task.search([('user_ids', 'in', user.id)])
        my_tasks = mine.filtered(lambda t: not t.parent_id)
        my_subtasks = mine.filtered(lambda t: t.parent_id)
        reviews = Task.search([
            ('reviewer_id', '=', user.id),
            ('pmo_state', 'in', ['under_review', 'testing'])])
        upcoming = mine.filtered(
            lambda t: t.date_deadline and
            t.pmo_state not in TASK_DONE_STATES + ['cancelled']).sorted(
            key=lambda t: t.date_deadline)[:15]
        timesheets = request.env['account.analytic.line'].search(
            [('user_id', '=', user.id), ('project_id', '!=', False)])
        done = mine.filtered(lambda t: t.pmo_state in TASK_DONE_STATES)

        def serialise(task):
            """Render one task row of the personal dashboard."""
            return {
                'id': task.id, 'name': task.display_name,
                'project': task.project_id.display_name,
                'deadline': str(task.date_deadline or ''),
                'state': task.pmo_state,
                'completion': task.completion_percentage,
                'overdue': task.is_overdue,
            }

        return {
            'role': 'user',
            'my_tasks': [serialise(t) for t in my_tasks[:25]],
            'my_task_ids': my_tasks.ids,
            'my_subtasks': [serialise(t) for t in my_subtasks[:25]],
            'my_subtask_ids': my_subtasks.ids,
            'pending_reviews': [serialise(t) for t in reviews[:25]],
            'pending_review_ids': reviews.ids,
            'upcoming': [serialise(t) for t in upcoming],
            'logged_hours': round(sum(timesheets.mapped('unit_amount')), 2),
            'logged_hours_ids': timesheets.ids,
            'personal_progress': (
                round(100.0 * len(done) / len(mine), 1) if mine else 0.0),
            'open_count': len(mine) - len(done),
            'done_count': len(done),
        }
