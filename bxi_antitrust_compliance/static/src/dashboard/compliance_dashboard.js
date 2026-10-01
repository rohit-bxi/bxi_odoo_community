/** @odoo-module **/

import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";

const MODEL = "antitrust.dashboard";
const AUTO_REFRESH_MS = 5 * 60 * 1000;
const RING_RADIUS = 36;
const RING_LENGTH = 2 * Math.PI * RING_RADIUS;

export class ComplianceDashboard extends Component {
    static template = "bxi_antitrust_compliance.ComplianceDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            data: null,
            months: 6,
            hidden: {},
        });
        this.ringLength = RING_LENGTH;
        onWillStart(() => this.load());
        onMounted(() => {
            this.timer = setInterval(() => this.load(), AUTO_REFRESH_MS);
        });
        onWillUnmount(() => clearInterval(this.timer));
    }

    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call(MODEL, "get_dashboard_data", [], { months: this.state.months });
        } finally {
            this.state.loading = false;
        }
    }

    // ------------------------------------------------------------------
    // Navigation
    // ------------------------------------------------------------------
    async openKpi(key) {
        const action = await this.orm.call(MODEL, "open_kpi", [key]);
        await this.action.doAction(action);
    }

    async openTrend(seriesKey, monthStart) {
        const action = await this.orm.call(MODEL, "open_trend", [seriesKey, monthStart]);
        await this.action.doAction(action);
    }

    async openPolicy(policyId, state = false) {
        const action = await this.orm.call(MODEL, "open_policy", [policyId, state]);
        await this.action.doAction(action);
    }

    async openRecord(item) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: item.model,
            res_id: item.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    onKeyOpen(ev, callback) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            callback();
        }
    }

    // ------------------------------------------------------------------
    // Filters
    // ------------------------------------------------------------------
    async onPeriodChange(ev) {
        this.state.months = parseInt(ev.target.value, 10);
        await this.load();
    }

    toggleSeries(key) {
        this.state.hidden[key] = !this.state.hidden[key];
    }

    // ------------------------------------------------------------------
    // Display helpers
    // ------------------------------------------------------------------
    get refreshedLabel() {
        const refreshed = this.state.data?.refreshed;
        return refreshed ? formatDateTime(deserializeDateTime(refreshed), { format: "HH:mm" }) : "";
    }

    get visibleSeries() {
        return (this.state.data?.trend.series || []).filter((series) => !this.state.hidden[series.key]);
    }

    get trendMax() {
        const values = this.visibleSeries.flatMap((series) => series.values);
        return Math.max(1, ...values);
    }

    get trendTotal() {
        return this.visibleSeries.reduce((sum, series) => sum + series.values.reduce((a, b) => a + b, 0), 0);
    }

    barHeight(value) {
        if (!value) {
            return "0%";
        }
        return `${Math.max(4, (100 * value) / this.trendMax)}%`;
    }

    ringOffset(rate) {
        return RING_LENGTH * (1 - Math.min(100, Math.max(0, rate || 0)) / 100);
    }

    rateTone(rate) {
        return rate >= 90 ? "success" : rate >= 60 ? "warning" : "danger";
    }

    get outcomeMax() {
        return Math.max(1, ...(this.state.data?.outcomes || []).map((outcome) => outcome.count));
    }

    ageLabel(days) {
        if (days <= 0) {
            return "today";
        }
        return days === 1 ? "1 day" : `${days} days`;
    }

    formatValue(kpi) {
        if (kpi.value === null || kpi.value === undefined) {
            return "—";
        }
        return kpi.is_rate ? `${kpi.value}%` : kpi.value;
    }
}

registry.category("actions").add("bxi_compliance_dashboard", ComplianceDashboard);
