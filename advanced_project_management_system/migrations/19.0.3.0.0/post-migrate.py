# -*- coding: utf-8 -*-
#############################################################################
#    Cybrosys Technologies Pvt. Ltd.
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    License LGPL-3.
#############################################################################
"""Backfill the PMO references and statuses on existing records.

New records get their sequence from ``create``, but records that already
existed before this version would keep the literal default, so they are
numbered here in one pass.
"""
import logging

_logger = logging.getLogger(__name__)


def _backfill_codes(env, model, field, sequence_code):
    """Assign a sequence value to every record still holding the default.

    :param env: the environment.
    :param model: technical model name.
    :param field: name of the reference field to fill.
    :param sequence_code: ``ir.sequence`` code to draw numbers from.
    """
    records = env[model].with_context(active_test=False).search(
        ['|', (field, '=', False), (field, '=', 'New')])
    for record in records:
        record[field] = env['ir.sequence'].next_by_code(sequence_code) or 'New'
    _logger.info("PMO: numbered %s %s records.", len(records), model)


def migrate(cr, version):
    """Backfill PMO references and align task statuses.

    :param cr: database cursor.
    :param version: version being upgraded from.
    """
    if not version:
        return
    from odoo import SUPERUSER_ID, api
    env = api.Environment(cr, SUPERUSER_ID, {})

    _backfill_codes(env, 'project.project', 'project_code',
                    'project.project.pmo')
    _backfill_codes(env, 'project.milestone', 'milestone_code',
                    'project.milestone.pmo')
    _backfill_codes(env, 'project.task', 'task_code', 'project.task.pmo')

    # Existing sub-tasks must sit on the sub-task status list.
    subtasks = env['project.task'].with_context(active_test=False).search(
        [('parent_id', '!=', False),
         ('pmo_state', 'not in', ['not_started', 'in_progress', 'blocked',
                                  'under_review', 'completed', 'closed',
                                  'cancelled'])])
    subtasks.write({'pmo_state': 'not_started'})
    _logger.info("PMO: realigned %s sub-task statuses.", len(subtasks))
