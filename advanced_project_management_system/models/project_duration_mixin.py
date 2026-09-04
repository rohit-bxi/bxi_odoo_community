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
from datetime import date, datetime, time

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

SECONDS_PER_HOUR = 3600.0
SECONDS_PER_DAY = 86400.0


class ProjectDurationMixin(models.AbstractModel):
    """Reusable mixin that adds a Days/Hours duration unit selection and a
    duration computed from the record's start date and its end date
    (deadline / expiration date).

    Every model inheriting this mixin declares which of its own fields hold
    the start and the end of the period through ``_duration_start_field`` and
    ``_duration_end_field``. Because ``api.depends`` cannot be expressed on
    field names that are only known in the concrete model, each inheriting
    model re-declares ``_compute_duration`` with the proper decorator and
    simply calls ``super()``.
    """
    _name = 'project.duration.mixin'
    _description = 'Project Duration Mixin (Days / Hours)'

    # Overridden by the inheriting models.
    _duration_start_field = 'start_date'
    _duration_end_field = 'date_deadline'

    duration_type = fields.Selection(
        selection=[('days', 'Days'), ('hours', 'Hours')],
        string='Duration Unit', default='days', required=True,
        help="Unit used to express the duration between the start date and "
             "the deadline of this record.")
    duration = fields.Float(
        string='Duration', compute='_compute_duration', store=True,
        readonly=True, digits=(16, 2),
        help="Duration between the start date and the deadline, expressed "
             "in the selected duration unit.")
    duration_display = fields.Char(
        string='Planned Duration', compute='_compute_duration_display',
        help="Human readable duration, e.g. '5.00 Days' or '12.50 Hours'.")

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    @api.model
    def _duration_to_datetime(self, value, end_of_day=False):
        """Normalise a Date or Datetime value into a naive datetime so that
        both field types can be subtracted from each other.

        :param value: a ``date``, ``datetime`` or falsy value.
        :param end_of_day: unused placeholder kept for readability; dates are
            always anchored at midnight so that a whole number of days is
            returned for Date based models.
        :return: a ``datetime`` instance or ``False``.
        """
        if not value:
            return False
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, time.min)
        return False

    def _get_duration_bounds(self):
        """Return the (start, end) datetimes of the record.

        :return: tuple of two ``datetime`` values or ``False``.
        """
        self.ensure_one()
        start = self._duration_to_datetime(self[self._duration_start_field])
        end = self._duration_to_datetime(self[self._duration_end_field],
                                         end_of_day=True)
        return start, end

    # ---------------------------------------------------------
    # Compute methods
    # ---------------------------------------------------------

    def _compute_duration(self):
        """Compute the duration between the start date and the deadline in
        the unit chosen on ``duration_type``.

        Days are counted as calendar days (24h). When either bound is missing
        the duration falls back to 0.
        """
        for record in self:
            start, end = record._get_duration_bounds()
            if not start or not end or end < start:
                record.duration = 0.0
                continue
            seconds = (end - start).total_seconds()
            if record.duration_type == 'hours':
                record.duration = round(seconds / SECONDS_PER_HOUR, 2)
            else:
                record.duration = round(seconds / SECONDS_PER_DAY, 2)

    @api.depends('duration', 'duration_type')
    def _compute_duration_display(self):
        """Build a readable label combining the duration and its unit."""
        labels = dict(
            self._fields['duration_type']._description_selection(self.env))
        for record in self:
            unit = labels.get(record.duration_type, '')
            record.duration_display = '%.2f %s' % (record.duration or 0.0,
                                                   unit)

    # ---------------------------------------------------------
    # Constraint methods
    # ---------------------------------------------------------

    def _check_duration_dates(self):
        """Make sure the deadline is never earlier than the start date.

        :raises ValidationError: when the deadline precedes the start date.
        """
        for record in self:
            start, end = record._get_duration_bounds()
            if start and end and end < start:
                raise ValidationError(_(
                    "The deadline of \"%s\" cannot be earlier than its start "
                    "date.", record.display_name))
