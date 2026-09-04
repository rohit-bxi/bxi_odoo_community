# -*- coding: utf-8 -*-
#############################################################################
#    Cybrosys Technologies Pvt. Ltd.
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    License LGPL-3.
#############################################################################
"""Fold the redundant ``project_stage_id`` field into core ``stage_id``.

This version drops ``project.project.project_stage_id``, a second Many2one
to ``project.project.stage`` that duplicated the native ``stage_id`` field
without ever being kept in sync with it. Any project whose two stage values
had drifted apart would silently disappear from Kanban boards and filters
grouped on the native field, since only ``project_stage_id`` was updated by
the "Mass Update Stage" wizard. Before the column is dropped, carry its
value over to ``stage_id`` wherever the two disagree, so no in-flight work
is lost.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Copy ``project_stage_id`` onto ``stage_id`` before the field is removed.

    :param cr: database cursor.
    :param version: version being upgraded from.
    """
    if not version:
        return
    cr.execute(
        """SELECT column_name FROM information_schema.columns
           WHERE table_name = 'project_project'
           AND column_name = 'project_stage_id'"""
    )
    if not cr.fetchone():
        return
    cr.execute(
        """UPDATE project_project
           SET stage_id = project_stage_id
           WHERE project_stage_id IS NOT NULL
           AND project_stage_id IS DISTINCT FROM stage_id"""
    )
    _logger.info("PMO: realigned %s project(s) onto the native stage_id "
                 "before dropping project_stage_id.", cr.rowcount)
