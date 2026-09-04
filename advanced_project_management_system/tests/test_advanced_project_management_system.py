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
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestAdvancedProjectManagementSystem(TransactionCase):

    def setUp(self):
        super().setUp()
        self.category = self.env['project.category'].create({
            'name': 'Development',
            'is_active': True,
        })
        self.project = self.env['project.project'].create({
            'name': 'Test Project Alpha',
            'project_category_id': self.category.id,
        })
        self.checklist = self.env['project.checklist'].create({
            'name': 'Setup Environment',
            'description': 'Configure the development environment',
            'company_id': self.env.company.id,
        })
        self.task = self.env['project.task'].create({
            'name': 'Initial Task',
            'project_id': self.project.id,
            'task_type': 'task',
        })

    def test_01_project_category_creation(self):
        self.assertEqual(self.category.name, 'Development')
        self.assertTrue(self.category.is_active)

    def test_02_project_creation_with_category(self):
        self.assertEqual(self.project.name, 'Test Project Alpha')
        self.assertEqual(self.project.project_category_id.id, self.category.id)

    def test_03_project_checklist_creation(self):
        self.assertEqual(self.checklist.name, 'Setup Environment')
        self.assertEqual(self.checklist.description,
                         'Configure the development environment')
        self.assertEqual(self.checklist.company_id.id, self.env.company.id)

    def test_04_project_checklist_info_creation(self):
        checklist_info = self.env['project.checklist.info'].create({
            'checklist_id': self.checklist.id,
            'project_id': self.project.id,
            'state': 'new',
        })
        self.assertEqual(checklist_info.project_id.id, self.project.id)
        self.assertEqual(checklist_info.state, 'new')

    def test_05_checklist_info_complete_action(self):
        checklist_info = self.env['project.checklist.info'].create({
            'checklist_id': self.checklist.id,
            'project_id': self.project.id,
            'state': 'new',
        })
        checklist_info.action_set_checklist_complete()
        self.assertEqual(checklist_info.state, 'done')

    def test_06_checklist_info_cancel_action(self):
        checklist_info = self.env['project.checklist.info'].create({
            'checklist_id': self.checklist.id,
            'project_id': self.project.id,
            'state': 'new',
        })
        checklist_info.action_set_checklist_close()
        self.assertEqual(checklist_info.state, 'cancel')

    def test_07_checklist_progress_updates_on_complete(self):
        info1 = self.env['project.checklist.info'].create({
            'checklist_id': self.checklist.id,
            'project_id': self.project.id,
            'state': 'new',
        })
        info2 = self.env['project.checklist.info'].create({
            'checklist_id': self.checklist.id,
            'project_id': self.project.id,
            'state': 'new',
        })
        info1.action_set_checklist_complete()
        self.assertGreater(self.project.checklist_progress, 0)

    def test_08_task_creation_with_type(self):
        self.assertEqual(self.task.name, 'Initial Task')
        self.assertEqual(self.task.task_type, 'task')
        self.assertEqual(self.task.project_id.id, self.project.id)

    def test_09_task_type_bug(self):
        bug_task = self.env['project.task'].create({
            'name': 'Bug Task',
            'project_id': self.project.id,
            'task_type': 'bug',
        })
        self.assertEqual(bug_task.task_type, 'bug')

    def test_10_task_type_subtask(self):
        subtask = self.env['project.task'].create({
            'name': 'Sub Task',
            'project_id': self.project.id,
            'task_type': 'subtask',
        })
        self.assertEqual(subtask.task_type, 'subtask')

    def test_13_task_document_count(self):
        self.env['ir.attachment'].create({
            'name': 'test_document.pdf',
            'res_model': 'project.task',
            'res_id': self.task.id,
            'datas': b'',
        })
        self.task._compute_document_count()
        self.assertEqual(self.task.document_count, 1)

    def test_14_project_document_count(self):
        self.env['ir.attachment'].create({
            'name': 'project_document.pdf',
            'res_model': 'project.project',
            'res_id': self.project.id,
            'datas': b'',
        })
        self.project._compute_document_count()
        self.assertEqual(self.project.document_count, 1)

    def test_15_project_issue_creation(self):
        issue = self.env['project.issue'].create({
            'project_id': self.project.id,
            'task_id': self.task.id,
            'summary': 'Test issue summary',
            'priority': '1',
            'state': 'new',
        })
        self.assertNotEqual(issue.name, 'new')
        self.assertEqual(issue.state, 'new')
        self.assertEqual(issue.project_id.id, self.project.id)

    def test_16_project_issue_state_transitions(self):
        issue = self.env['project.issue'].create({
            'project_id': self.project.id,
            'summary': 'State transition test',
            'state': 'new',
        })
        issue.state = 'progress'
        self.assertEqual(issue.state, 'progress')
        issue.state = 'done'
        self.assertEqual(issue.state, 'done')

    def test_17_project_issue_count(self):
        self.env['project.issue'].create({
            'project_id': self.project.id,
            'summary': 'Issue one',
        })
        self.env['project.issue'].create({
            'project_id': self.project.id,
            'summary': 'Issue two',
        })
        self.project._compute_issue_count()
        self.assertEqual(self.project.issue_count, 2)

    def test_18_project_url_shortcut_with_link(self):
        self.project.url_link = 'https://www.example.com'
        self.project.url_name = 'Example Site'
        self.project._compute_url_shortcut()
        self.assertTrue(self.project.is_active)
        self.assertEqual(self.project.url_shortcut, 'https://www.example.com')

    def test_19_project_url_shortcut_without_link(self):
        self.project.url_link = False
        self.project._compute_url_shortcut()
        self.assertFalse(self.project.is_active)
        self.assertEqual(self.project.url_shortcut, 'Add Link')

    def test_22_project_task_type_with_multiple_users(self):
        user1 = self.env['res.users'].create({
            'name': 'Test User One',
            'login': 'testuser1_apms@test.com',
        })
        user2 = self.env['res.users'].create({
            'name': 'Test User Two',
            'login': 'testuser2_apms@test.com',
        })
        stage = self.env['project.task.type'].create({
            'name': 'In Review',
            'user_ids': [(6, 0, [user1.id, user2.id])],
        })
        self.assertIn(user1.id, stage.user_ids.ids)
        self.assertIn(user2.id, stage.user_ids.ids)

    def test_23_multiple_categories_for_projects(self):
        cat2 = self.env['project.category'].create({
            'name': 'Marketing',
            'is_active': True,
        })
        project2 = self.env['project.project'].create({
            'name': 'Marketing Campaign',
            'project_category_id': cat2.id,
        })
        self.assertEqual(project2.project_category_id.name, 'Marketing')
        self.assertNotEqual(project2.project_category_id.id,
                            self.project.project_category_id.id)

    def test_24_issue_sequence_auto_generated(self):
        issue1 = self.env['project.issue'].create({
            'project_id': self.project.id,
            'summary': 'First issue',
        })
        issue2 = self.env['project.issue'].create({
            'project_id': self.project.id,
            'summary': 'Second issue',
        })
        self.assertNotEqual(issue1.name, issue2.name)
        self.assertNotEqual(issue1.name, 'new')

    # ------------------------------------------------------------------
    # Days / Hours duration
    # ------------------------------------------------------------------

    def test_25_task_duration_in_days(self):
        task = self.env['project.task'].create({
            'name': 'Duration in days',
            'project_id': self.project.id,
            'start_date': '2026-01-01 08:00:00',
            'date_deadline': '2026-01-06 08:00:00',
            'duration_type': 'days',
        })
        self.assertEqual(task.duration, 5.0)

    def test_26_task_duration_in_hours(self):
        task = self.env['project.task'].create({
            'name': 'Duration in hours',
            'project_id': self.project.id,
            'start_date': '2026-01-01 08:00:00',
            'date_deadline': '2026-01-01 20:30:00',
            'duration_type': 'hours',
        })
        self.assertEqual(task.duration, 12.5)

    def test_27_subtask_duration(self):
        subtask = self.env['project.task'].create({
            'name': 'Sub-task duration',
            'project_id': self.project.id,
            'parent_id': self.task.id,
            'start_date': '2026-02-01 09:00:00',
            'date_deadline': '2026-02-01 17:00:00',
            'duration_type': 'hours',
        })
        self.assertEqual(subtask.duration, 8.0)

    def test_28_duration_without_bounds_is_zero(self):
        self.assertEqual(self.task.duration, 0.0)

    def test_29_deadline_before_start_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env['project.task'].create({
                'name': 'Backwards task',
                'project_id': self.project.id,
                'start_date': '2026-03-10 09:00:00',
                'date_deadline': '2026-03-01 09:00:00',
            })

    def test_30_milestone_duration_in_days(self):
        milestone = self.env['project.milestone'].create({
            'name': 'Beta release',
            'project_id': self.project.id,
            'start_date': '2026-04-01',
            'deadline': '2026-04-11',
            'duration_type': 'days',
        })
        self.assertEqual(milestone.duration, 10.0)

    def test_31_project_duration_in_days(self):
        self.project.write({
            'date_start': '2026-05-01',
            'date': '2026-05-31',
            'duration_type': 'days',
        })
        self.assertEqual(self.project.duration, 30.0)

    def test_32_issue_duration_and_display(self):
        issue = self.env['project.issue'].create({
            'project_id': self.project.id,
            'summary': 'Duration issue',
            'start_date': '2026-06-01 08:00:00',
            'deadline': '2026-06-01 14:00:00',
            'duration_type': 'hours',
        })
        self.assertEqual(issue.duration, 6.0)
        self.assertEqual(issue.duration_display, '6.00 Hours')

    def test_33_duration_unit_switch_recomputes(self):
        task = self.env['project.task'].create({
            'name': 'Unit switch',
            'project_id': self.project.id,
            'start_date': '2026-07-01 00:00:00',
            'date_deadline': '2026-07-03 00:00:00',
            'duration_type': 'days',
        })
        self.assertEqual(task.duration, 2.0)
        task.duration_type = 'hours'
        self.assertEqual(task.duration, 48.0)

    # ------------------------------------------------------------------
    # Access levels
    # ------------------------------------------------------------------

    def test_34_access_level_groups_exist(self):
        for xml_id in ('group_apms_user', 'group_apms_manager',
                       'group_apms_admin'):
            group = self.env.ref(
                'advanced_project_management_system.%s' % xml_id)
            self.assertTrue(group)

    def test_35_manager_implies_user_and_admin_implies_manager(self):
        user_group = self.env.ref(
            'advanced_project_management_system.group_apms_user')
        manager_group = self.env.ref(
            'advanced_project_management_system.group_apms_manager')
        admin_group = self.env.ref(
            'advanced_project_management_system.group_apms_admin')
        self.assertIn(user_group, manager_group.all_implied_ids)
        self.assertIn(manager_group, admin_group.all_implied_ids)
        self.assertIn(
            self.env.ref('project.group_project_manager'),
            admin_group.all_implied_ids)

    def test_36_user_level_only_sees_own_tasks(self):
        level_user = self.env['res.users'].create({
            'name': 'Level User',
            'login': 'apms_level_user',
            'group_ids': [(6, 0, [self.env.ref(
                'advanced_project_management_system.group_apms_user').id])],
        })
        mine = self.env['project.task'].create({
            'name': 'Mine',
            'project_id': self.project.id,
            'user_ids': [(6, 0, [level_user.id])],
        })
        other = self.env['project.task'].create({
            'name': 'Not mine',
            'project_id': self.project.id,
        })
        visible = self.env['project.task'].with_user(level_user).search([
            ('id', 'in', [mine.id, other.id])])
        self.assertIn(mine, visible)
        self.assertNotIn(other, visible)

    # ------------------------------------------------------------------
    # PMO governance model
    # ------------------------------------------------------------------

    def test_37_pmo_references_are_sequenced(self):
        self.assertNotEqual(self.project.project_code, 'New')
        self.assertNotEqual(self.task.task_code, 'New')
        milestone = self.env['project.milestone'].create({
            'name': 'Kickoff', 'project_id': self.project.id})
        self.assertNotEqual(milestone.milestone_code, 'New')

    def test_38_risk_rating_thresholds(self):
        risk = self.env['project.risk'].create({
            'title': 'Vendor slippage',
            'project_id': self.project.id,
            'probability': 'very_low',
            'impact': 'low',
        })
        self.assertEqual(risk.risk_score, 1)
        self.assertEqual(risk.risk_rating, 'green')
        risk.write({'probability': 'medium', 'impact': 'high'})
        self.assertEqual(risk.risk_score, 9)
        self.assertEqual(risk.risk_rating, 'amber')
        risk.write({'probability': 'very_high', 'impact': 'critical'})
        self.assertEqual(risk.risk_score, 20)
        self.assertEqual(risk.risk_rating, 'red')

    def test_39_risk_closure_stamps_date(self):
        risk = self.env['project.risk'].create({
            'title': 'Scope creep', 'project_id': self.project.id})
        self.assertTrue(risk.is_open)
        risk.action_close()
        self.assertFalse(risk.is_open)
        self.assertTrue(risk.closure_date)

    def test_40_project_rolls_up_task_and_milestone_counts(self):
        milestone = self.env['project.milestone'].create({
            'name': 'Phase 1', 'project_id': self.project.id})
        done = self.env['project.task'].create({
            'name': 'Done task', 'project_id': self.project.id,
            'milestone_id': milestone.id, 'pmo_state': 'completed'})
        self.env['project.task'].create({
            'name': 'Open task', 'project_id': self.project.id,
            'milestone_id': milestone.id, 'pmo_state': 'in_progress'})
        self.assertEqual(self.project.total_milestone_count, 1)
        self.assertGreaterEqual(self.project.total_task_count, 3)
        self.assertIn(done, self.project.task_ids)
        self.assertEqual(milestone.total_task_count, 2)
        self.assertEqual(milestone.completed_task_count, 1)
        self.assertEqual(milestone.completion_percentage, 50.0)

    def test_41_open_risk_and_issue_counters(self):
        self.env['project.risk'].create({
            'title': 'Open risk', 'project_id': self.project.id})
        self.env['project.risk'].create({
            'title': 'Closed risk', 'project_id': self.project.id,
            'state': 'closed'})
        self.env['project.issue'].create({
            'project_id': self.project.id, 'summary': 'Open issue'})
        self.assertEqual(self.project.open_risk_count, 1)
        self.assertEqual(self.project.open_issue_count, 1)

    def test_42_subtask_status_is_restricted(self):
        subtask = self.env['project.task'].create({
            'name': 'Child', 'project_id': self.project.id,
            'parent_id': self.task.id})
        self.assertEqual(subtask.pmo_state, 'not_started')
        with self.assertRaises(ValidationError):
            subtask.pmo_state = 'backlog'

    def test_43_completing_a_task_stamps_completion(self):
        task = self.env['project.task'].create({
            'name': 'To complete', 'project_id': self.project.id})
        task.pmo_state = 'completed'
        self.assertTrue(task.actual_completion_date)
        self.assertEqual(task.completion_percentage, 100.0)

    def test_44_completion_percentage_is_bounded(self):
        with self.assertRaises(ValidationError):
            self.task.completion_percentage = 150.0

    def test_45_task_cannot_block_itself(self):
        with self.assertRaises(ValidationError):
            self.task.blocked_by_id = self.task.id

    def test_46_issue_pmo_state_syncs_legacy_state(self):
        issue = self.env['project.issue'].create({
            'project_id': self.project.id, 'summary': 'Sync test'})
        issue.action_resolve()
        self.assertEqual(issue.pmo_state, 'resolved')
        self.assertEqual(issue.state, 'done')
        self.assertTrue(issue.resolution_date)
        self.assertFalse(issue.is_open)

    def test_47_project_health_turns_red_on_red_risk(self):
        self.env['project.risk'].create({
            'title': 'Critical exposure', 'project_id': self.project.id,
            'probability': 'very_high', 'impact': 'critical'})
        self.assertEqual(self.project.red_risk_count, 1)
        self.assertEqual(self.project.health_status, 'red')

    def test_48_team_allocation_rejects_bad_percentage(self):
        with self.assertRaises(ValidationError):
            self.env['project.team.member'].create({
                'project_id': self.project.id,
                'user_id': self.env.user.id,
                'role': 'technical_lead',
                'allocation_percentage': 150.0,
            })

    def test_49_team_roles_lookup(self):
        self.env['project.team.member'].create({
            'project_id': self.project.id, 'user_id': self.env.user.id,
            'role': 'reviewer_qa'})
        reviewers = self.project._get_team_users(['reviewer_qa'])
        self.assertIn(self.env.user, reviewers)
        self.assertFalse(self.project._get_team_users(['cxo']))

    def test_50_pmo_and_cxo_groups_chain(self):
        admin = self.env.ref(
            'advanced_project_management_system.group_apms_admin')
        pmo = self.env.ref('advanced_project_management_system.group_apms_pmo')
        cxo = self.env.ref('advanced_project_management_system.group_apms_cxo')
        self.assertIn(admin, pmo.all_implied_ids)
        self.assertIn(pmo, cxo.all_implied_ids)

    def test_51_project_approval_flow(self):
        self.project.action_submit_for_approval()
        self.assertEqual(self.project.approval_state, 'to_approve')
        self.project.action_approve()
        self.assertEqual(self.project.approval_state, 'approved')
        self.assertEqual(self.project.pmo_state, 'approved')
        self.assertEqual(self.project.approved_by_id, self.env.user)

    def test_52_milestone_acceptance_sets_is_reached(self):
        milestone = self.env['project.milestone'].create({
            'name': 'Go live', 'project_id': self.project.id})
        milestone.action_approve_milestone()
        self.assertEqual(milestone.pmo_state, 'accepted')
        self.assertTrue(milestone.is_reached)
        self.assertEqual(milestone.approved_by_id, self.env.user)
