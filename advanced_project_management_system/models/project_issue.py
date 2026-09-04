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
from odoo import _, api, fields, models

from .project_pmo_selection import (
    ISSUE_CLOSED_STATES, ISSUE_STATES, PMO_PRIORITIES, SEVERITIES,
)


class ProjectIssue(models.Model):
    """
    Model for recording and tracking issues related to projects and tasks,
    including a Days/Hours duration computed from the issue start date and
    its deadline.
    """
    _name = "project.issue"
    _inherit = ['project.duration.mixin']
    _description = 'Project and task issue'
    _order = 'create_date desc, id desc'

    _duration_start_field = 'start_date'
    _duration_end_field = 'deadline'

    user_id = fields.Many2one("res.users", string="Assigned to",
                              default=lambda self: self.env.user,
                              help="The person who is responsible to solve "
                                   "the issue")
    summary = fields.Text(string='Issue summary', help="Adding project issue")
    email = fields.Char(string="Email", help="Email address")
    project_id = fields.Many2one('project.project', string="Project",
                                 help="To know issue noticed in which project")
    task_id = fields.Many2one('project.task', string="Task",
                              help="To know issue noticed in which task",
                              domain="[('project_id', '=', project_id)]")
    priority = fields.Selection([('0', 'Low'), ('1', 'High')], default='0',
                                string="Priority")
    milestone_id = fields.Many2one(
        'project.milestone', string='Milestone',
        domain="[('project_id', '=', project_id)]", ondelete='set null',
        help="Milestone the issue was raised against.")
    pmo_priority = fields.Selection(
        selection=PMO_PRIORITIES, string='Issue Priority', default='medium',
        required=True, help="Low, Medium, High or Critical.")
    severity = fields.Selection(
        selection=SEVERITIES, string='Severity', default='minor',
        required=True, help="Minor, Major, Critical or Showstopper.")
    pmo_state = fields.Selection(
        selection=ISSUE_STATES, string='Issue Status', default='new',
        required=True, group_expand='_group_expand_pmo_state',
        help="PMO lifecycle status of the issue.")
    reported_by_id = fields.Many2one(
        'res.users', string='Reported By', readonly=True,
        default=lambda self: self.env.user,
        help="User who raised the issue.")
    target_resolution_date = fields.Datetime(
        string='Target Resolution Date',
        help="Date the issue is committed to be resolved by.")
    resolution = fields.Html(string='Resolution',
                             help="How the issue was resolved.")
    resolution_date = fields.Datetime(string='Resolution Date', readonly=True,
                                      copy=False)
    is_open = fields.Boolean(string='Open', compute='_compute_issue_flags',
                             store=True,
                             help="Technical flag used by the dashboards.")
    is_escalated = fields.Boolean(string='Escalated',
                                  compute='_compute_issue_flags', store=True)
    age_days = fields.Integer(string='Age (Days)',
                              compute='_compute_issue_flags', store=True)
    tag_ids = fields.Many2many('project.tags', string='Tags',
                               help='Set the tags')
    partner_id = fields.Many2one('res.partner', string="Contact",
                                 help="Know about the contact details")
    name = fields.Char(string='Number', default='new',
                       help='To track the issue reference')
    description = fields.Text(string='Description',
                              help="To add the issue in detail")
    extra_info = fields.Text(string="Extra Info",
                             help="To add some extra information")
    state = fields.Selection([('new', 'New'), ('progress', 'In Progress'),
                              ('done', 'Done'), ('cancel', 'Cancel')],
                             default='new', string='State',
                             help='Project issue pipeline stages')
    create_date = fields.Datetime(string="Create Date", readonly=True,
                                  help='For tracking the record creation date')
    start_date = fields.Datetime(
        string='Start Date', copy=False, default=fields.Datetime.now,
        help="Date on which the work on this issue starts. Used together "
             "with the deadline to compute the duration.")
    deadline = fields.Datetime(
        string='Deadline', copy=False,
        help="Date by which this issue should be resolved.")
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company,
        help="Company owning this issue.")

    # ---------------------------------------------------------
    # Compute methods
    # ---------------------------------------------------------

    @api.model
    def _group_expand_pmo_state(self, states, domain):
        """Always show every issue status column in grouped views.

        :param states: the states currently present in the data.
        :param domain: the active domain.
        :return: the full list of status keys.
        """
        return [key for key, _label in ISSUE_STATES]

    @api.depends('pmo_state', 'create_date', 'resolution_date')
    def _compute_issue_flags(self):
        """Derive the open, escalated and ageing indicators."""
        today = fields.Date.context_today(self)
        for issue in self:
            issue.is_open = issue.pmo_state not in ISSUE_CLOSED_STATES
            issue.is_escalated = issue.pmo_state == 'escalated'
            if issue.create_date:
                end = (issue.resolution_date.date()
                       if issue.resolution_date and not issue.is_open
                       else today)
                issue.age_days = (end - issue.create_date.date()).days
            else:
                issue.age_days = 0

    @api.depends('start_date', 'deadline', 'duration_type')
    def _compute_duration(self):
        """Recompute the issue duration whenever its bounds change."""
        return super()._compute_duration()

    # ---------------------------------------------------------
    # Constraint methods
    # ---------------------------------------------------------

    @api.constrains('start_date', 'deadline')
    def _check_duration_dates(self):
        """Reject issues whose deadline precedes their start date."""
        return super()._check_duration_dates()

    # ---------------------------------------------------------
    # Overrides
    # ---------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """
        Overrides create to automatically generate a unique issue reference
        number from the sequence.
        :param vals_list: List of dictionaries of field values.
        :return: Created recordset.
        """
        for vals in vals_list:
            if vals.get('name', 'new') == 'new':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'project.issue') or 'new'
        return super().create(vals_list)

    def write(self, vals):
        """Keep the legacy state aligned and stamp the resolution date.

        :param vals: values being written.
        :return: True.
        """
        if 'pmo_state' in vals:
            mapping = {
                'new': 'new', 'assigned': 'progress', 'analysis': 'progress',
                'mitigation': 'progress', 'escalated': 'progress',
                'pending_decision': 'progress', 'resolved': 'done',
                'verified': 'done', 'closed': 'done', 'rejected': 'cancel',
            }
            vals.setdefault('state', mapping.get(vals['pmo_state'], 'new'))
            if vals['pmo_state'] in ISSUE_CLOSED_STATES:
                vals.setdefault('resolution_date', fields.Datetime.now())
            else:
                vals['resolution_date'] = False
        return super().write(vals)

    # ---------------------------------------------------------
    # Action methods
    # ---------------------------------------------------------

    def action_escalate(self):
        """Escalate the issue to the PMO."""
        self.write({'pmo_state': 'escalated'})

    def action_resolve(self):
        """Mark the issue as resolved."""
        self.write({'pmo_state': 'resolved'})

    def action_close_issue(self):
        """Close the issue."""
        self.write({'pmo_state': 'closed'})
