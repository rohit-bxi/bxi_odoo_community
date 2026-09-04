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
#############################################################################
"""Clean up everything the task checklist feature left behind.

The task checklist models, their tables and the task side columns are dropped
here so that upgrading from 19.0.1.0.0 does not leave orphaned data around.
"""
import logging

_logger = logging.getLogger(__name__)

OBSOLETE_MODELS = [
    'project.task.checklist.info',
    'project.task.checklist.template',
    'project.task.checklist',
    'project.task.checklist.import',
]

OBSOLETE_TABLES = [
    'project_task_checklist_info',
    'project_task_checklist_template_project_task_checklist_rel',
    'project_task_project_task_checklist_template_rel',
    'project_task_checklist_template',
    'project_task_checklist',
    'project_task_checklist_import',
]

OBSOLETE_TASK_COLUMNS = ['checklist_progress']


def migrate(cr, version):
    """Drop the obsolete task checklist schema.

    :param cr: database cursor.
    :param version: version being upgraded from.
    """
    if not version:
        return

    # Remove the ORM metadata first so Odoo stops advertising the models.
    cr.execute("""
        DELETE FROM ir_model_fields
         WHERE model IN %s
    """, (tuple(OBSOLETE_MODELS),))
    cr.execute("""
        DELETE FROM ir_model_data
         WHERE model = 'ir.model'
           AND res_id IN (SELECT id FROM ir_model WHERE model IN %s)
    """, (tuple(OBSOLETE_MODELS),))
    cr.execute("DELETE FROM ir_model WHERE model IN %s",
               (tuple(OBSOLETE_MODELS),))

    for table in OBSOLETE_TABLES:
        cr.execute('DROP TABLE IF EXISTS "%s" CASCADE' % table)

    for column in OBSOLETE_TASK_COLUMNS:
        cr.execute('ALTER TABLE project_task DROP COLUMN IF EXISTS "%s"'
                   % column)

    _logger.info("Advanced Project Management System: task checklist data "
                 "removed.")
