# -*- coding: utf-8 -*-
#############################################################################
#    Cybrosys Technologies Pvt. Ltd.
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    License LGPL-3.
#############################################################################
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .project_pmo_selection import TEAM_ROLES


class ProjectTeamMember(models.Model):
    """One line of the team allocation structure of a project.

    A user can appear several times on the same project as long as the role
    differs, which is what lets a Technical Lead also be a Reviewer.
    """
    _name = 'project.team.member'
    _description = 'Project Team Allocation'
    _order = 'project_id, role, id'

    project_id = fields.Many2one('project.project', string='Project',
                                 required=True, ondelete='cascade',
                                 index=True,
                                 help="Project this allocation belongs to.")
    user_id = fields.Many2one('res.users', string='Member', required=True,
                              help="Allocated user.")
    role = fields.Selection(selection=TEAM_ROLES, string='Role', required=True,
                            default='team_member',
                            help="Role played by this member on the project.")
    allocation_percentage = fields.Float(
        string='Allocation (%)', default=100.0,
        help="Share of the member's capacity dedicated to this project.")
    date_start = fields.Date(string='From',
                             help="First day of the allocation.")
    date_end = fields.Date(string='To', help="Last day of the allocation.")
    email = fields.Char(string='Email', related='user_id.email', readonly=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 related='project_id.company_id', store=True)
    active = fields.Boolean(string='Active', default=True)

    _user_role_uniq = models.Constraint(
        'unique(project_id, user_id, role)',
        'This member is already allocated to that project with the same role.')

    @api.depends('user_id', 'role')
    def _compute_display_name(self):
        """Show the member together with the role they play."""
        labels = dict(TEAM_ROLES)
        for member in self:
            member.display_name = '%s (%s)' % (
                member.user_id.name or '', labels.get(member.role, ''))

    @api.constrains('allocation_percentage')
    def _check_allocation_percentage(self):
        """Keep the allocation within a sensible 0 to 100 range.

        :raises ValidationError: when the percentage is out of range.
        """
        for member in self:
            if not 0 < member.allocation_percentage <= 100:
                raise ValidationError(_(
                    "The allocation of %s must be greater than 0 and at most "
                    "100%%.", member.user_id.name))

    @api.constrains('date_start', 'date_end')
    def _check_allocation_dates(self):
        """Reject an allocation ending before it starts.

        :raises ValidationError: when the end date precedes the start date.
        """
        for member in self:
            if member.date_start and member.date_end and \
                    member.date_end < member.date_start:
                raise ValidationError(_(
                    "The allocation of %s ends before it starts.",
                    member.user_id.name))
