# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo import api, fields, models


class ProjectTask(models.Model):
    """
    Inherits from 'project.task' to add document counting, task
    categorisation and a Days/Hours duration computed from the task start
    date and its deadline. The same model backs sub-tasks, so sub-tasks get
    the very same duration behaviour.
    """
    _name = 'project.task'
    _inherit = ['project.task', 'project.duration.mixin']

    _duration_start_field = 'start_date'
    _duration_end_field = 'date_deadline'

    document_count = fields.Integer(string='Documents',
                                    compute='_compute_document_count',
                                    help="For getting document count")
    task_type = fields.Selection([
        ('task', 'Task'),
        ('subtask', 'Subtask'),
        ('bug', 'Bug'),
    ], string='Task Type', default="task")
    start_date = fields.Datetime(
        string='Start Date', copy=False, tracking=True, index=True,
        help="Date on which the work on this task starts. Used together "
             "with the deadline to compute the duration.")

    # ---------------------------------------------------------
    # Compute methods
    # ---------------------------------------------------------

    def _compute_document_count(self):
        """
        Computes the number of documents (attachments) associated with the task.
        """
        for rec in self:
            attachment_ids = self.env['ir.attachment'].search(
                [('res_model', '=', 'project.task'), ('res_id', '=', rec.id)])
            rec.document_count = len(attachment_ids)

    @api.depends('start_date', 'date_deadline', 'duration_type')
    def _compute_duration(self):
        """Recompute the task duration whenever its bounds change."""
        return super()._compute_duration()

    # ---------------------------------------------------------
    # Onchange methods
    # ---------------------------------------------------------

    @api.onchange('stage_id')
    def _onchange_stage_id(self):
        """
        Automatically assigns the task to users specified in the new stage.
        """
        if self.stage_id.user_ids:
            self.user_ids = self.stage_id.user_ids

    @api.onchange('parent_id')
    def _onchange_parent_id_task_type(self):
        """Flag a task as a sub-task as soon as it gets a parent task."""
        for task in self:
            if task.parent_id and task.task_type == 'task':
                task.task_type = 'subtask'

    # ---------------------------------------------------------
    # Constraint methods
    # ---------------------------------------------------------

    @api.constrains('start_date', 'date_deadline')
    def _check_duration_dates(self):
        """Reject tasks whose deadline precedes their start date."""
        return super()._check_duration_dates()

    # ---------------------------------------------------------
    # Action methods
    # ---------------------------------------------------------

    def action_task_document(self):
        """
        Opens a kanban/form view of documents attached to the current task.
        :return: action dictionary.
        """
        return {
            'name': 'Documents',
            'type': 'ir.actions.act_window',
            'res_model': 'ir.attachment',
            'view_mode': 'kanban,form',
            'res_id': self._origin.id,
            'domain': [
                ('res_id', '=', self._origin.id),
                ('res_model', '=', 'project.task')],
        }

    def task_mass_update(self):
        """
        Opens the wizard for mass updating task details.
        :return: action dictionary.
        """
        return {
            'name': 'Mass Update Tasks',
            'type': 'ir.actions.act_window',
            'res_model': 'project.task.mass.update',
            'target': 'new',
            'view_mode': 'form',
        }

    def task_overdue_notification(self):
        """
        Sends email notifications to responsible users for overdue tasks.
        This method is designed to be called via a scheduled action.
        """
        if self.env['ir.config_parameter'].sudo().get_param(
                'res.config.settings.is_overdue_notification'):
            today = fields.Datetime.now()
            task_ids = self.search([])
            for task in task_ids:
                if task.stage_id.name not in (
                        'Done',
                        'Canceled') and task.date_deadline and \
                        task.date_deadline < today:
                    mail_template = task.env.ref(
                        'advanced_project_management_system.'
                        'task_due_email_notification')
                    mail_template.send_mail(task.id, force_send=True)

    # ---------------------------------------------------------
    # Private methods
    # ---------------------------------------------------------

    def _get_user_emails(self):
        """
        Collects email addresses of users assigned to overdue tasks.
        :return: A list of user login/email strings.
        """
        emails = []
        task_ids = self.search(
            [('date_deadline', '<', fields.Datetime.now())])
        for task in task_ids:
            if task.stage_id.name not in ('Done', 'Canceled'):
                for user in task.user_ids:
                    emails.append(user.login)
        return emails
