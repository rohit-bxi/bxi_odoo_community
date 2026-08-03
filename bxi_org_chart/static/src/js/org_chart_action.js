/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class BxiOrgChartAction extends Component {
    static template = "bxi_org_chart.OrgChartAction";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            companyName: "",
            boardTitle: "Reporting to The Board",
            totalEmployees: 0,
            totalDepartments: 0,
            directBoardReports: 0,
            rootNodes: [],
            expandedNodes: {}, // nodeId: boolean
            searchQuery: "",
            zoomScale: 0.8,
            selectedEmployeeModal: null, // Employee node object for modal popup
            isFullscreen: false,
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData() {
        this.state.loading = true;
        try {
            const data = await this.orm.call("hr.employee", "get_org_chart_tree_data", []);
            this.state.companyName = data.company_name || "";
            this.state.boardTitle = data.board_title || "Reporting to The Board";
            this.state.totalEmployees = data.total_employees || 0;
            this.state.totalDepartments = data.total_departments || 0;
            this.state.directBoardReports = data.direct_board_reports || 0;
            this.state.rootNodes = data.root_nodes || [];
            
            // MINIMIZED BY DEFAULT: Only root level (Level 1) is expanded, subordinates are collapsed
            const initialExpanded = {};
            for (const root of this.state.rootNodes) {
                initialExpanded[root.id] = true;
            }
            this.state.expandedNodes = initialExpanded;
        } catch (error) {
            console.error("Failed to load Org Chart data:", error);
        } finally {
            this.state.loading = false;
        }
    }

    toggleExpand(nodeId, ev) {
        if (ev) {
            ev.stopPropagation();
        }
        this.state.expandedNodes[nodeId] = !this.state.expandedNodes[nodeId];
    }

    isExpanded(nodeId) {
        return !!this.state.expandedNodes[nodeId];
    }

    expandAll() {
        const allExpanded = {};
        const collectIds = (nodes) => {
            for (const node of nodes) {
                allExpanded[node.id] = true;
                if (node.children) {
                    collectIds(node.children);
                }
            }
        };
        collectIds(this.state.rootNodes);
        this.state.expandedNodes = allExpanded;
    }

    collapseAll() {
        this.state.expandedNodes = {};
    }

    zoomIn() {
        this.state.zoomScale = Math.min(this.state.zoomScale + 0.15, 2.0);
    }

    zoomOut() {
        this.state.zoomScale = Math.max(this.state.zoomScale - 0.15, 0.4);
    }

    resetZoom() {
        this.state.zoomScale = 0.8;
    }

    toggleFullscreen() {
        this.state.isFullscreen = !this.state.isFullscreen;
    }

    onSearchInput(ev) {
        this.state.searchQuery = ev.target.value.toLowerCase().trim();
        if (this.state.searchQuery) {
            this.expandPathToMatches(this.state.rootNodes, this.state.searchQuery);
        }
    }

    expandPathToMatches(nodes, query) {
        let hasMatchInBranch = false;
        for (const node of nodes) {
            const isMatch = (node.name && node.name.toLowerCase().includes(query)) ||
                            (node.job_title && node.job_title.toLowerCase().includes(query)) ||
                            (node.department && node.department.toLowerCase().includes(query));

            let childMatched = false;
            if (node.children && node.children.length > 0) {
                childMatched = this.expandPathToMatches(node.children, query);
            }

            if (isMatch || childMatched) {
                this.state.expandedNodes[node.id] = true;
                hasMatchInBranch = true;
            }
        }
        return hasMatchInBranch;
    }

    isMatched(node) {
        if (!this.state.searchQuery) return false;
        const q = this.state.searchQuery;
        return (node.name && node.name.toLowerCase().includes(q)) ||
               (node.job_title && node.job_title.toLowerCase().includes(q)) ||
               (node.department && node.department.toLowerCase().includes(q));
    }

    openModal(node, ev) {
        if (ev) {
            ev.stopPropagation();
        }
        this.state.selectedEmployeeModal = node;
    }

    closeModal() {
        this.state.selectedEmployeeModal = null;
    }

    openEmployeeProfile(empId, ev) {
        if (ev) {
            ev.stopPropagation();
        }
        this.closeModal();
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.employee.public",
            res_id: empId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("bxi_org_chart_action", BxiOrgChartAction);
