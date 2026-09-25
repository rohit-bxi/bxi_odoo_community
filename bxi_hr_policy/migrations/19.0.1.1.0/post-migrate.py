# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Turn each existing policy document into a published version 1.

    Existing policies do not start asking employees for acknowledgement:
    HR can use "Request Acknowledgement" when they want to.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    policies = env['hr.company.policy'].with_context(active_test=False).search([])
    for policy in policies:
        if policy.version_ids or not policy.policy_document:
            continue
        policy.requires_acknowledgement = False
        env['hr.company.policy.version'].create({
            'policy_id': policy.id,
            'version_no': 1,
            'document': policy.policy_document,
            'filename': policy.policy_filename,
            'valid_from': policy.upload_date or policy.create_date.date(),
            'description': 'Initial version',
            'state': 'published',
            'published_date': policy.create_date,
        })
