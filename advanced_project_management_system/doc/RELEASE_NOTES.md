## Module <advanced_project_management_system>

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
