# -*- coding: utf-8 -*-
##############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2025-TODAY Cybrosys Technologies(<https://www.cybrosys.com>).
#    Author: AYANA KP @cybrosys(odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
import datetime

from odoo import http
from odoo.http import request

ADMIN_GROUP = 'advanced_project_management_system.group_apms_admin'
MANAGER_GROUP = 'advanced_project_management_system.group_apms_manager'
USER_GROUP = 'advanced_project_management_system.group_apms_user'
PROJECT_MANAGER_GROUP = 'project.group_project_manager'


class ProjectDashboard(http.Controller):
    """Feeds the project dashboard.

    Every endpoint resolves the access level of the current user first and
    then reads the records through that user's own environment, so the record
    rules shipped by ``advanced_project_management_system`` do the filtering
    and nothing can leak between levels.
    """

    # ------------------------------------------------------------------
    # Access level helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_access_level():
        """Return the access level of the current user.

        :return: one of ``'admin'``, ``'manager'`` or ``'user'``.
        """
        user = request.env.user
        if user.has_group(ADMIN_GROUP) or user.has_group(
                PROJECT_MANAGER_GROUP):
            return 'admin'
        if user.has_group(MANAGER_GROUP):
            return 'manager'
        return 'user'

    @staticmethod
    def _project_domain(level):
        """Build the project domain matching the given access level.

        :param level: the access level returned by ``_get_access_level``.
        :return: an Odoo domain (list of tuples).
        """
        if level == 'admin':
            return []
        user = request.env.user
        if level == 'manager':
            return ['|', '|',
                    ('user_id', '=', user.id),
                    ('message_partner_ids', 'in', [user.partner_id.id]),
                    ('task_ids.user_ids', 'in', user.id)]
        return ['|', ('user_id', '=', user.id),
                ('task_ids.user_ids', 'in', user.id)]

    @staticmethod
    def _task_domain(level, project_ids=None):
        """Build the task domain matching the given access level.

        :param level: the access level returned by ``_get_access_level``.
        :param project_ids: optional list of project ids to restrict to.
        :return: an Odoo domain (list of tuples).
        """
        domain = []
        if project_ids is not None:
            domain.append(('project_id', 'in', project_ids))
        if level == 'user':
            user = request.env.user
            domain += ['|', ('user_ids', 'in', user.id),
                       ('parent_id.user_ids', 'in', user.id)]
        return domain

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_date(value):
        """Render a Date or Datetime value as a plain string.

        :param value: the value stored on the record, may be falsy.
        :return: a string, empty when there is no value.
        """
        if not value:
            return ''
        if isinstance(value, datetime.datetime):
            return value.strftime('%Y-%m-%d %H:%M')
        return str(value)

    @classmethod
    def _serialise_task(cls, task, children):
        """Turn a task into the dictionary consumed by the dashboard.

        :param task: a ``project.task`` record.
        :param children: already serialised sub-tasks of this task.
        :return: a dictionary.
        """
        return {
            'id': task.id,
            'name': task.display_name,
            'stage': task.stage_id.display_name or '',
            'assignees': ', '.join(task.user_ids.mapped('name')),
            'start_date': cls._format_date(task.start_date),
            'deadline': cls._format_date(task.date_deadline),
            'duration': task.duration,
            'duration_type': task.duration_type,
            'milestone_id': task.milestone_id.id or False,
            'subtasks': children,
        }

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @http.route('/project/dashboard/tiles', auth='user', type='jsonrpc')
    def get_tiles_data(self):
        """Return the KPI tiles and the stage breakdown.

        :return: a dictionary of counters, record ids and the access level.
        """
        level = self._get_access_level()
        projects = request.env['project.project'].search(
            self._project_domain(level))
        tasks = request.env['project.task'].search(
            self._task_domain(level, projects.ids))
        parent_tasks = tasks.filtered(lambda t: not t.parent_id)
        subtasks = tasks.filtered(lambda t: t.parent_id)
        milestones = request.env['project.milestone'].search(
            [('project_id', 'in', projects.ids)])
        timesheets = request.env['account.analytic.line'].search(
            [('project_id', 'in', projects.ids)])

        stage_list = []
        stages = request.env['project.project.stage'].sudo().search([])
        projects_sudo = projects.sudo()
        for stage in stages:
            stage_list.append({
                'id': stage.id,
                'name': stage.display_name,
                'projects': len(projects_sudo.filtered(
                    lambda p, s=stage: p.stage_id == s)),
            })

        return {
            'access_level': level,
            'total_projects': len(projects),
            'total_projects_ids': projects.ids,
            'total_milestones': len(milestones),
            'total_milestones_ids': milestones.ids,
            'total_tasks': len(parent_tasks),
            'total_tasks_ids': parent_tasks.ids,
            'total_subtasks': len(subtasks),
            'total_subtasks_ids': subtasks.ids,
            'total_hours': round(sum(timesheets.mapped('unit_amount')), 2),
            'total_hours_ids': timesheets.ids,
            'project_stage_list': stage_list,
        }

    @http.route('/project/dashboard/hierarchy', auth='user', type='jsonrpc')
    def get_hierarchy(self, **kw):
        """Return the project / milestone / task / sub-task tree.

        Tasks that belong to a milestone are nested under that milestone;
        the remaining ones are listed directly under their project. Sub-tasks
        always sit under their parent task.

        :param kw: optional ``data`` dictionary carrying the active filters.
        :return: a dictionary with a ``projects`` key holding the tree.
        """
        level = self._get_access_level()
        data = kw.get('data') or {}
        domain = self._project_domain(level)
        selected_project = data.get('project')
        if selected_project and selected_project != 'null':
            domain = [('id', '=', int(selected_project))]
        projects = request.env['project.project'].search(domain)
        tasks = request.env['project.task'].search(
            self._task_domain(level, projects.ids))

        children_by_parent = {}
        for task in tasks:
            if task.parent_id:
                children_by_parent.setdefault(task.parent_id.id, []).append(
                    task)

        def serialise(task):
            """Recursively serialise a task and the sub-tasks below it."""
            children = [serialise(child)
                        for child in children_by_parent.get(task.id, [])]
            return self._serialise_task(task, children)

        result = []
        for project in projects:
            project_tasks = tasks.filtered(
                lambda t, p=project: t.project_id == p and not t.parent_id)
            milestones = []
            for milestone in request.env['project.milestone'].search(
                    [('project_id', '=', project.id)]):
                milestone_tasks = project_tasks.filtered(
                    lambda t, m=milestone: t.milestone_id == m)
                milestones.append({
                    'id': milestone.id,
                    'name': milestone.display_name,
                    'start_date': self._format_date(milestone.start_date),
                    'deadline': self._format_date(milestone.deadline),
                    'duration': milestone.duration,
                    'duration_type': milestone.duration_type,
                    'is_reached': milestone.is_reached,
                    'tasks': [serialise(t) for t in milestone_tasks],
                })
            loose_tasks = project_tasks.filtered(
                lambda t: not t.milestone_id)
            result.append({
                'id': project.id,
                'name': project.display_name,
                'manager': project.user_id.name or '',
                'stage': project.sudo().stage_id.display_name or '',
                'start_date': self._format_date(project.date_start),
                'deadline': self._format_date(project.date),
                'duration': project.duration,
                'duration_type': project.duration_type,
                'milestones': milestones,
                'tasks': [serialise(t) for t in loose_tasks],
            })
        return {'access_level': level, 'projects': result}

    @http.route('/project/task/count', auth='user', type='jsonrpc')
    def get_project_task_count(self):
        """Return the task count per project for the doughnut chart.

        :return: a dictionary with project labels, task counts and colours.
        """
        level = self._get_access_level()
        projects = request.env['project.project'].search(
            self._project_domain(level))
        names, totals, colors = [], [], []
        for project in projects:
            names.append(project.display_name)
            totals.append(request.env['project.task'].search_count(
                self._task_domain(level, [project.id])))
            colors.append(request.env['project.project'].get_color_code())
        return {'project': names, 'task': totals, 'color': colors}

    @http.route('/project/filter', auth='user', type='jsonrpc')
    def project_filter(self):
        """Return the projects available in the dashboard filter.

        :return: a list of ``{'id': .., 'name': ..}`` dictionaries.
        """
        level = self._get_access_level()
        projects = request.env['project.project'].search(
            self._project_domain(level))
        return [{'id': project.id, 'name': project.display_name}
                for project in projects]

    @http.route('/project/filter-apply', auth='user', type='jsonrpc')
    def project_filter_apply(self, **kw):
        """Recompute the KPI tiles for the selected filters.

        :param kw: a ``data`` dictionary with ``start_date``, ``end_date``
            and ``project`` entries. ``'null'`` means "not set".
        :return: a dictionary of counters and record ids.
        """
        data = kw.get('data') or {}
        level = self._get_access_level()
        domain = self._project_domain(level)

        start_date = data.get('start_date')
        end_date = data.get('end_date')
        selected_project = data.get('project')

        if selected_project and selected_project != 'null':
            domain = domain + [('id', '=', int(selected_project))]
        if start_date and start_date != 'null':
            domain = domain + [('date_start', '>=', datetime.datetime.strptime(
                start_date, '%Y-%m-%d').date())]
        if end_date and end_date != 'null':
            domain = domain + [('date_start', '<=', datetime.datetime.strptime(
                end_date, '%Y-%m-%d').date())]

        projects = request.env['project.project'].search(domain)
        tasks = request.env['project.task'].search(
            self._task_domain(level, projects.ids))
        parent_tasks = tasks.filtered(lambda t: not t.parent_id)
        subtasks = tasks.filtered(lambda t: t.parent_id)
        milestones = request.env['project.milestone'].search(
            [('project_id', 'in', projects.ids)])
        timesheets = request.env['account.analytic.line'].search(
            [('project_id', 'in', projects.ids)])

        return {
            'access_level': level,
            'total_projects': len(projects),
            'total_projects_ids': projects.ids,
            'total_milestones': len(milestones),
            'total_milestones_ids': milestones.ids,
            'total_tasks': len(parent_tasks),
            'total_tasks_ids': parent_tasks.ids,
            'total_subtasks': len(subtasks),
            'total_subtasks_ids': subtasks.ids,
            'total_hours': round(sum(timesheets.mapped('unit_amount')), 2),
            'total_hours_ids': timesheets.ids,
        }
