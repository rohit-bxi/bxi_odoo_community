## Module <advanced_project_management_system>

#### 04.09.2026
#### Version 19.0.4.0.2
#### FIX

- Moved the PMO identification fields (Project ID, Business Unit, Department,
  Project Owner, Project Coordinator, Priority, Health Status, Overall
  Progress %) and the Project Category / Duration fields out of the stat
  button row and into the Checklist tab, each in its own labeled group. Both
  had been anchored via `//field[@name='privacy_visibility']`, but core
  Odoo auto-inserts a hidden duplicate of that field inside the button box
  (to satisfy a stat button's `invisible` condition), and that duplicate
  matches first — so every one of these fields was rendering as an
  unlabeled, bare field jammed between the stat buttons instead of in the
  sheet body.

#### 04.09.2026
#### Version 19.0.4.0.1
#### FIX

- Hid the native `stage_id` statusbar on the project form: PMO Status
  (`pmo_state`) already covers the full lifecycle (Draft through Cancelled),
  so keeping the generic Kanban Stage bar alongside it was still redundant.
  Kanban board grouping, the list column and filters on `stage_id` are
  untouched, only the form header changes.

#### 04.09.2026
#### Version 19.0.4.0.0
#### FIX

- Removed `project_stage_id`, a second Many2one to `project.project.stage`
  that duplicated the native `stage_id` field without ever syncing to it,
  leaving the project form with two independent, unsynced stage bars and
  a "Mass Update Stage" wizard that only moved one of them. Existing
  projects are realigned onto `stage_id` on upgrade.
- Fixed a duplicate `view_project` record id in `project_project_views.xml`
  that silently discarded the Project Category list column: the two
  inherited views shared one external id, so the second overwrote the
  first in the database.

#### 04.09.2026
#### Version 19.0.3.0.0
#### ADD

- PMO governance model: Project > Milestone > Task > Sub-task / Issue / Risk,
  with a new `project.risk` register, `project.team.member` allocation and
  `project.business.unit`.
- Full PMO field set on projects, milestones, tasks and sub-tasks, including
  references, owners, planned and actual dates, roll-up counters, health
  status, approval trail, SLA, dependencies, blockers and quality fields.
- The six status workflows from the specification (project, milestone, task,
  sub-task, issue, risk) plus issue and risk priority, severity, probability,
  impact and RAG rating.
- Two extra access levels, PMO Head and CXO, on top of the existing
  Administrator, Manager and User levels.
- Thirteen PMO reports under Project > PMO > Reports.
- Scheduled action refreshing project health daily.

#### 04.09.2026
#### Version 19.0.2.0.0
#### UPDT

- Added Administrator / Manager / User access levels enforced through global
  record rules, a Days / Hours duration on projects, milestones, tasks,
  sub-tasks and issues, and removed the task checklist feature.

#### 30.05.2026
#### Version 19.0.1.0.0
#### ADD

- Initial commit for Advanced Project Management System.
