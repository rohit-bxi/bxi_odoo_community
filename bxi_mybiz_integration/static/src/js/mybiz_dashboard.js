/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const STATE_COLORS = {
    draft: "#adb5bd",
    submitted: "#4dabf7",
    manager_approval: "#f59f00",
    hr_approval: "#f76707",
    mybiz_pending: "#7048e8",
    approved: "#2f9e44",
    cancelled: "#e03131",
};

const MYBIZ_COLORS = {
    not_pushed: "#adb5bd",
    pending: "#f59f00",
    approved: "#2f9e44",
    booked: "#2f9e44",
    cancelled: "#e03131",
    failed: "#e03131",
};

class BxiMybizDashboard extends Component {
    static template = "bxi_mybiz_integration.DashboardTemplate";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({
            loaded: false,
            days: 90,
            total_requests: 0,
            state_counts: {},
            state_labels: {},
            mybiz_counts: {},
            mybiz_labels: {},
            success_rate: 0,
            pushed_count: 0,
            failed_count: 0,
            pending_manager: 0,
            pending_hr: 0,
            mybiz_pending: 0,
            avg_turnaround_days: 0,
            upcoming: [],
            recent_failures: [],
            dept_spend: [],
            max_dept_amount: 0,
            monthly_trend: [],
            max_month_count: 0,
            currency_symbol: "",
            is_admin: false,
            is_hr: false,
            is_manager: false,
            base_domain: [],
            recent_domain: [],
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData() {
        this.state.loaded = false;
        const result = await this.orm.call(
            "bxi.mybiz.dashboard",
            "get_dashboard_data",
            [],
            { days: this.state.days }
        );
        Object.assign(this.state, result);
        this.state.loaded = true;
    }

    async setDays(days) {
        this.state.days = days;
        await this.loadData();
    }

    stateColor(key) {
        return STATE_COLORS[key] || "#868e96";
    }

    mybizColor(key) {
        return MYBIZ_COLORS[key] || "#868e96";
    }

    barWidth(value, max) {
        if (!max) {
            return 0;
        }
        return Math.max(Math.round((value / max) * 100), value > 0 ? 4 : 0);
    }

    openRequest(id) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "travel.request",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    /**
     * Drill down from a dashboard tile/bar into the matching travel
     * requests, e.g. clicking the "Pending HR Approval" KPI or the
     * "HR Approval" bar in the status funnel.
     */
    openList(extraDomain, title) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: title,
            res_model: "travel.request",
            views: [[false, "list"], [false, "form"]],
            domain: extraDomain,
            target: "current",
        });
    }

    openTotalRequests() {
        this.openList(this.state.recent_domain, "Total Requests");
    }

    openPushFailures() {
        this.openList(
            [...this.state.recent_domain, ["mybiz_status", "=", "failed"]],
            "myBiz Push Failures"
        );
    }

    openSuccessfulPushes() {
        this.openList(
            [...this.state.recent_domain,
                ["mybiz_status", "in", ["pending", "approved", "booked"]]],
            "myBiz Push Successes"
        );
    }

    openTurnaroundTracked() {
        this.openList(
            [...this.state.recent_domain, ["hr_approved_date", "!=", false]],
            "Approved With Turnaround Data"
        );
    }

    openPendingManager() {
        this.openList(
            [...this.state.base_domain, ["state", "=", "manager_approval"]],
            "Pending Manager Approval"
        );
    }

    openPendingHr() {
        this.openList(
            [...this.state.base_domain, ["state", "=", "hr_approval"]],
            "Pending HR Approval"
        );
    }

    openMybizPending() {
        this.openList(
            [...this.state.base_domain, ["state", "=", "mybiz_pending"]],
            "Awaiting myBiz Confirmation"
        );
    }

    openByState(key) {
        this.openList(
            [...this.state.recent_domain, ["state", "=", key]],
            this.state.state_labels[key] || key
        );
    }

    openByMybizStatus(key) {
        this.openList(
            [...this.state.recent_domain, ["mybiz_status", "=", key]],
            this.state.mybiz_labels[key] || key
        );
    }

    openByDepartment(dept) {
        const filter = dept.department_id
            ? ["department_id", "=", dept.department_id]
            : ["department_id", "=", false];
        this.openList(
            [...this.state.recent_domain, filter],
            dept.department
        );
    }

    openByMonth(month) {
        this.openList(
            [
                ...this.state.base_domain,
                ["request_date", ">=", month.date_from],
                ["request_date", "<", month.date_to],
            ],
            month.label
        );
    }
}

registry.category("actions").add("bxi_mybiz_dashboard_tag", BxiMybizDashboard);
export { BxiMybizDashboard };
