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
"""Shared PMO selection lists.

Every status, priority, severity and rating required by the PMO governance
model lives here so that the same wording is reused by the models, the views
and the dashboards.
"""

PROJECT_STATES = [
    ('draft', 'Draft'),
    ('planning', 'Planning'),
    ('approved', 'Approved'),
    ('active', 'Active'),
    ('on_hold', 'On Hold'),
    ('at_risk', 'At Risk'),
    ('delayed', 'Delayed'),
    ('uat', 'UAT'),
    ('completed', 'Completed'),
    ('closed', 'Closed'),
    ('cancelled', 'Cancelled'),
]
PROJECT_OPEN_STATES = ['draft', 'planning', 'approved', 'active', 'on_hold',
                       'at_risk', 'delayed', 'uat']
PROJECT_DONE_STATES = ['completed', 'closed']

MILESTONE_STATES = [
    ('not_started', 'Not Started'),
    ('planned', 'Planned'),
    ('in_progress', 'In Progress'),
    ('pending_approval', 'Pending Approval'),
    ('completed', 'Completed'),
    ('accepted', 'Accepted'),
    ('delayed', 'Delayed'),
    ('blocked', 'Blocked'),
    ('cancelled', 'Cancelled'),
]
MILESTONE_DONE_STATES = ['completed', 'accepted']

TASK_STATES = [
    ('backlog', 'Backlog'),
    ('assigned', 'Assigned'),
    ('not_started', 'Not Started'),
    ('in_progress', 'In Progress'),
    ('on_hold', 'On Hold'),
    ('blocked', 'Blocked'),
    ('under_review', 'Under Review'),
    ('testing', 'Testing'),
    ('rework', 'Rework'),
    ('completed', 'Completed'),
    ('closed', 'Closed'),
    ('cancelled', 'Cancelled'),
]
TASK_DONE_STATES = ['completed', 'closed']
TASK_BLOCKED_STATES = ['blocked', 'on_hold']

SUBTASK_STATES = [
    ('not_started', 'Not Started'),
    ('in_progress', 'In Progress'),
    ('blocked', 'Blocked'),
    ('under_review', 'Under Review'),
    ('completed', 'Completed'),
    ('closed', 'Closed'),
    ('cancelled', 'Cancelled'),
]

ISSUE_STATES = [
    ('new', 'New'),
    ('assigned', 'Assigned'),
    ('analysis', 'Analysis in Progress'),
    ('mitigation', 'Mitigation in Progress'),
    ('escalated', 'Escalated'),
    ('pending_decision', 'Pending Decision'),
    ('resolved', 'Resolved'),
    ('verified', 'Verified'),
    ('closed', 'Closed'),
    ('rejected', 'Rejected'),
]
ISSUE_CLOSED_STATES = ['resolved', 'verified', 'closed', 'rejected']

RISK_STATES = [
    ('identified', 'Identified'),
    ('assessed', 'Assessed'),
    ('mitigation_planned', 'Mitigation Planned'),
    ('mitigation', 'Mitigation in Progress'),
    ('monitoring', 'Monitoring'),
    ('escalated', 'Escalated'),
    ('triggered', 'Triggered'),
    ('closed', 'Closed'),
    ('accepted', 'Accepted'),
]
RISK_CLOSED_STATES = ['closed', 'accepted']

PMO_PRIORITIES = [
    ('low', 'Low'),
    ('medium', 'Medium'),
    ('high', 'High'),
    ('critical', 'Critical'),
]

SEVERITIES = [
    ('minor', 'Minor'),
    ('major', 'Major'),
    ('critical', 'Critical'),
    ('showstopper', 'Showstopper'),
]

HEALTH_STATUSES = [
    ('green', 'Green'),
    ('amber', 'Amber'),
    ('red', 'Red'),
]

RISK_PROBABILITIES = [
    ('very_low', 'Very Low'),
    ('low', 'Low'),
    ('medium', 'Medium'),
    ('high', 'High'),
    ('very_high', 'Very High'),
]
RISK_PROBABILITY_SCORE = {'very_low': 1, 'low': 2, 'medium': 3, 'high': 4,
                          'very_high': 5}

RISK_IMPACTS = [
    ('low', 'Low'),
    ('medium', 'Medium'),
    ('high', 'High'),
    ('critical', 'Critical'),
]
RISK_IMPACT_SCORE = {'low': 1, 'medium': 2, 'high': 3, 'critical': 4}

RISK_RATINGS = [
    ('green', 'Green'),
    ('amber', 'Amber'),
    ('red', 'Red'),
]

APPROVAL_STATES = [
    ('not_required', 'Not Required'),
    ('to_approve', 'To Approve'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
]

TEAM_ROLES = [
    ('cxo', 'CXO'),
    ('pmo_head', 'PMO Head'),
    ('project_manager', 'Project Manager'),
    ('functional_lead', 'Functional Lead'),
    ('technical_lead', 'Technical Lead'),
    ('team_member', 'Team Member'),
    ('reviewer_qa', 'Reviewer / QA'),
    ('stakeholder', 'Stakeholder'),
]

TEST_STATUSES = [
    ('not_applicable', 'Not Applicable'),
    ('not_started', 'Not Started'),
    ('in_progress', 'In Progress'),
    ('passed', 'Passed'),
    ('failed', 'Failed'),
]
