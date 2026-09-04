/** @odoo-module */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { Component, onMounted, onWillStart, useRef, useState } from "@odoo/owl";

const ACCESS_LEVEL_LABELS = {
    admin: _t("Administrator"),
    manager: _t("Manager"),
    user: _t("User"),
};

export class ProjectDashboard extends Component {
    static template = "ProjectDashboard";
    static props = {};

    /**
     * Initialise the services, the refs and the reactive state.
     */
    setup() {
        this.action = useService("action");
        this.notification = useService("notification");

        this.project_doughnut = useRef("project_doughnut");
        this.project_selection = useRef("project_selection");
        this.start_date = useRef("start_date");
        this.end_date = useRef("end_date");

        this.chart = null;

        this.state = useState({
            accessLevel: "user",
            accessLevelLabel: ACCESS_LEVEL_LABELS.user,
            projectOptions: [],
            hierarchy: [],
            projectStageList: [],
            expanded: {},
            totalProjects: 0,
            totalMilestones: 0,
            totalTasks: 0,
            totalSubtasks: 0,
            totalHours: 0,
            projectIds: [],
            milestoneIds: [],
            taskIds: [],
            subtaskIds: [],
            timesheetIds: [],
        });

        onWillStart(async () => {
            await this.loadAll();
        });
        onMounted(async () => {
            await this.renderTaskChart();
        });
    }

    // ------------------------------------------------------------------
    // Data loading
    // ------------------------------------------------------------------

    /**
     * Load the tiles, the filter options and the project hierarchy.
     */
    async loadAll() {
        const [tiles, projects, hierarchy] = await Promise.all([
            rpc("/project/dashboard/tiles"),
            rpc("/project/filter"),
            rpc("/project/dashboard/hierarchy", { data: this.getFilters() }),
        ]);
        this.applyTiles(tiles);
        this.state.projectStageList = tiles.project_stage_list || [];
        this.state.projectOptions = projects || [];
        this.setHierarchy(hierarchy.projects || []);
    }

    /**
     * Copy a tiles payload into the reactive state.
     *
     * @param {Object} data payload returned by the tiles or filter endpoint.
     */
    applyTiles(data) {
        this.state.accessLevel = data.access_level;
        this.state.accessLevelLabel =
            ACCESS_LEVEL_LABELS[data.access_level] || ACCESS_LEVEL_LABELS.user;
        this.state.totalProjects = data.total_projects || 0;
        this.state.totalMilestones = data.total_milestones || 0;
        this.state.totalTasks = data.total_tasks || 0;
        this.state.totalSubtasks = data.total_subtasks || 0;
        this.state.totalHours = data.total_hours || 0;
        this.state.projectIds = data.total_projects_ids || [];
        this.state.milestoneIds = data.total_milestones_ids || [];
        this.state.taskIds = data.total_tasks_ids || [];
        this.state.subtaskIds = data.total_subtasks_ids || [];
        this.state.timesheetIds = data.total_hours_ids || [];
    }

    /**
     * Store the hierarchy and expand the first project so the tree is never
     * shown fully collapsed.
     *
     * @param {Array} projects serialised project tree.
     */
    setHierarchy(projects) {
        this.state.hierarchy = projects;
        this.state.expanded = {};
        if (projects.length) {
            this.state.expanded[`project-${projects[0].id}`] = true;
        }
    }

    /**
     * Read the current value of the three filter inputs.
     *
     * @returns {Object} the filter payload expected by the controller.
     */
    getFilters() {
        return {
            start_date: (this.start_date.el && this.start_date.el.value) || "null",
            end_date: (this.end_date.el && this.end_date.el.value) || "null",
            project:
                (this.project_selection.el && this.project_selection.el.value) ||
                "null",
        };
    }

    // ------------------------------------------------------------------
    // Tree helpers
    // ------------------------------------------------------------------

    /**
     * Tell whether a node of the tree is currently expanded.
     *
     * @param {string} type "project", "milestone" or "task".
     * @param {number} id record id.
     * @returns {boolean}
     */
    isOpen(type, id) {
        return Boolean(this.state.expanded[`${type}-${id}`]);
    }

    /**
     * Expand or collapse a node of the tree.
     *
     * @param {string} type "project", "milestone" or "task".
     * @param {number} id record id.
     */
    toggle(type, id) {
        const key = `${type}-${id}`;
        this.state.expanded[key] = !this.state.expanded[key];
    }

    /**
     * Return the short label of a duration unit.
     *
     * @param {string} durationType "days" or "hours".
     * @returns {string}
     */
    unitLabel(durationType) {
        return durationType === "hours" ? _t(" Hours") : _t(" Days");
    }

    // ------------------------------------------------------------------
    // Charts
    // ------------------------------------------------------------------

    /**
     * Draw the doughnut chart counting the tasks of every visible project.
     */
    async renderTaskChart() {
        if (!this.project_doughnut.el || typeof Chart === "undefined") {
            return;
        }
        const data = await rpc("/project/task/count");
        if (this.chart) {
            this.chart.destroy();
        }
        this.chart = new Chart(this.project_doughnut.el, {
            type: "doughnut",
            data: {
                labels: data.project,
                datasets: [
                    {
                        backgroundColor: data.color,
                        data: data.task,
                    },
                ],
            },
            options: {
                legend: { position: "left" },
                cutoutPercentage: 40,
                responsive: true,
            },
        });
    }

    // ------------------------------------------------------------------
    // Filters
    // ------------------------------------------------------------------

    /**
     * Recompute the tiles and the tree whenever a filter changes.
     */
    async onChangeFilter() {
        const filters = this.getFilters();
        const [tiles, hierarchy] = await Promise.all([
            rpc("/project/filter-apply", { data: filters }),
            rpc("/project/dashboard/hierarchy", { data: filters }),
        ]);
        this.applyTiles(tiles);
        this.setHierarchy(hierarchy.projects || []);
    }

    /**
     * Clear every filter and reload the dashboard from scratch.
     */
    async resetFilters() {
        if (this.start_date.el) {
            this.start_date.el.value = "";
        }
        if (this.end_date.el) {
            this.end_date.el.value = "";
        }
        if (this.project_selection.el) {
            this.project_selection.el.value = "null";
        }
        await this.loadAll();
        await this.renderTaskChart();
        this.notification.add(_t("Filters have been reset"), {
            type: "success",
        });
    }

    /**
     * Reload every dataset without touching the filters.
     */
    async reload() {
        await this.loadAll();
        await this.renderTaskChart();
    }

    // ------------------------------------------------------------------
    // Drill down actions
    // ------------------------------------------------------------------

    /**
     * Open a list/form action restricted to the given ids.
     *
     * @param {string} name action title.
     * @param {string} model technical model name.
     * @param {Array} ids record ids to show.
     * @param {Array} views view descriptors, defaults to list then form.
     */
    openRecords(name, model, ids, views) {
        this.action.doAction({
            name: name,
            type: "ir.actions.act_window",
            res_model: model,
            domain: [["id", "in", ids || []]],
            views: views || [
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
        });
    }

    /** Open the visible projects. */
    openProjects() {
        this.openRecords(_t("Projects"), "project.project", this.state.projectIds, [
            [false, "kanban"],
            [false, "form"],
        ]);
    }

    /** Open the visible milestones. */
    openMilestones() {
        this.openRecords(
            _t("Milestones"),
            "project.milestone",
            this.state.milestoneIds
        );
    }

    /** Open the visible top level tasks. */
    openTasks() {
        this.openRecords(_t("Tasks"), "project.task", this.state.taskIds);
    }

    /** Open the visible sub-tasks. */
    openSubtasks() {
        this.openRecords(_t("Sub-tasks"), "project.task", this.state.subtaskIds);
    }

    /** Open the timesheet lines behind the recorded hours. */
    openTimesheets() {
        this.openRecords(
            _t("Timesheets"),
            "account.analytic.line",
            this.state.timesheetIds,
            [[false, "list"]]
        );
    }
}

registry.category("actions").add("project_dashboard", ProjectDashboard);
