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


class ProjectMilestone(models.Model):
    """Adds a start date and a Days/Hours duration to project milestones.

    The core ``deadline`` field is reused as the end of the period so the
    duration always reflects the real milestone planning.
    """
    _name = 'project.milestone'
    _inherit = ['project.milestone', 'project.duration.mixin']

    _duration_start_field = 'start_date'
    _duration_end_field = 'deadline'

    start_date = fields.Date(
        string='Start Date', copy=False, tracking=True,
        help="Date on which the work towards this milestone starts. Used "
             "together with the deadline to compute the duration.")

    # ---------------------------------------------------------
    # Compute methods
    # ---------------------------------------------------------

    @api.depends('start_date', 'deadline', 'duration_type')
    def _compute_duration(self):
        """Recompute the milestone duration whenever its bounds change."""
        return super()._compute_duration()

    # ---------------------------------------------------------
    # Constraint methods
    # ---------------------------------------------------------

    @api.constrains('start_date', 'deadline')
    def _check_duration_dates(self):
        """Reject milestones whose deadline precedes their start date."""
        return super()._check_duration_dates()
