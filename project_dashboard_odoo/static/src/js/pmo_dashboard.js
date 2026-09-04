/** @odoo-module */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { Component, onWillStart, useState } from "@odoo/owl";

const ROLE_LABELS = {
    cxo: _t("CXO"),
    pmo: _t("PMO"),
    manager: _t("Manager"),
    user: _t("User"),
};

const ROLE_ENDPOINTS = {
    cxo: "/project/pmo/cxo",
    pmo: "/project/pmo/pmo",
    manager: "/project/pmo/manager",
    user: "/project/pmo/user",
};

export class PmoDashboard extends Component {
    static template = "PmoDashboard";
    static props = {};

    /**
     * Resolve the roles the user may open, then load the broadest one.
     */
    setup() {
        this.action = useService("action");
        this.state = useState({
            roles: [],
            role: "user",
            loading: true,
            data: {},
        });

        onWillStart(async () => {
            const info = await rpc("/project/pmo/roles");
            this.state.roles = info.roles;
            this.state.role = info.default_role;
            await this.loadRole(this.state.role);
        });
    }

    /**
     * Fetch and store the payload of one role dashboard.
     *
     * @param {string} role one of "cxo", "pmo", "manager" or "user".
     */
    async loadRole(role) {
        this.state.loading = true;
        this.state.role = role;
        this.state.data = await rpc(ROLE_ENDPOINTS[role]);
        this.state.loading = false;
    }

    /**
     * Human readable label of a role key.
     *
     * @param {string} role the role key.
     * @returns {string}
     */
    roleLabel(role) {
        return ROLE_LABELS[role] || role;
    }

    /**
     * Bootstrap contextual class matching a Green / Amber / Red value.
     *
     * @param {string} value the health or rating value.
     * @returns {string} a bootstrap background class.
     */
    ragClass(value) {
        if (value === "red") {
            return "bg-danger";
        }
        if (value === "amber") {
            return "bg-warning text-dark";
        }
        return "bg-success";
    }

    /**
     * Shade a heatmap cell according to how many risks it holds.
     *
     * @param {Object} cell one heatmap cell.
     * @returns {string} an inline style string.
     */
    heatStyle(cell) {
        if (!cell.count) {
            return "background-color: rgba(0,0,0,0.03);";
        }
        const intensity = Math.min(0.15 + cell.count * 0.15, 0.85);
        return `background-color: rgba(220, 53, 69, ${intensity}); color: #fff;`;
    }

    /**
     * Open a set of records in a regular Odoo action.
     *
     * @param {string} name the action title.
     * @param {string} model the technical model name.
     * @param {Array} ids the record ids to display.
     * @param {string} [firstView] the first view type to open.
     */
    open(name, model, ids, firstView) {
        this.action.doAction({
            name: name,
            type: "ir.actions.act_window",
            res_model: model,
            domain: [["id", "in", ids || []]],
            views: [
                [false, firstView || "list"],
                [false, "form"],
            ],
            target: "current",
        });
    }

    /**
     * Open a single record in its form view.
     *
     * @param {string} model the technical model name.
     * @param {number} id the record id.
     */
    openRecord(model, id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("pmo_dashboard", PmoDashboard);
