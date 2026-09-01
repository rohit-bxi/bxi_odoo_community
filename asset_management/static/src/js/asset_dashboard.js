/** @odoo-module **/

import { Component, onWillStart, onMounted, useState, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";

class AssetDashboard extends Component {
    static template = "asset_management.DashboardTemplate";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loaded: false,
            active_tab: "overview",
            filters: {
                department_id: "",
                asset_type_id: "",
                employee_id: "",
                location: "",
                vendor_id: "",
                status: "all",
            },
            filter_options: {
                departments: [],
                asset_types: [],
                employees: [],
                locations: [],
                vendors: [],
                statuses: [],
            },
            data: {},
            table_search_query: "",
        });

        // Overview Chart Canvas Refs
        this.vendorNbvChartRef = useRef("vendorNbvChart");
        this.vendorWarrantyChartRef = useRef("vendorWarrantyChart");
        this.deptStatusChartRef = useRef("deptStatusChart");
        this.conditionChartRef = useRef("conditionChart");

        // Summary Chart Canvas Refs
        this.typeCountChartRef = useRef("typeCountChart");
        this.typeValChartRef = useRef("typeValChart");

        // Department Chart Canvas Refs
        this.deptNbvChartRef = useRef("deptNbvChart");
        this.deptCountChartRef = useRef("deptCountChart");
        this.deptStatusMatrixChartRef = useRef("deptStatusMatrixChart");

        // Vendor Chart Canvas Refs
        this.vendorAnalysisNbvChartRef = useRef("vendorAnalysisNbvChart");
        this.vendorAnalysisWarrantyChartRef = useRef("vendorAnalysisWarrantyChart");
        this.vendorMaintChartRef = useRef("vendorMaintChart");

        // Trends Chart Canvas Refs
        this.trendsDualChartRef = useRef("trendsDualChart");
        this.trendsNbvChartRef = useRef("trendsNbvChart");
        this.trendsMaintChartRef = useRef("trendsMaintChart");

        // Chart.js Instances tracking
        this.chartInstances = {};

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.loadData();
            this.state.loaded = true;
        });

        onMounted(() => {
            this.renderCurrentTabCharts();
        });
    }

    // ─── RPC Data Loader ──────────────────────────────────────────────────────
    async loadData() {
        try {
            const result = await this.orm.call(
                "asset.dashboard",
                "get_dashboard_data",
                [],
                { filters: this.state.filters }
            );

            this.state.data = result || {};
            if (result && result.filters) {
                this.state.filter_options = result.filters;
            }
        } catch (error) {
            console.error("Failed to load asset dashboard data:", error);
        }
    }

    // ─── Filter & Navigation Handlers ─────────────────────────────────────────
    async onFilterChange(key, value) {
        this.state.filters[key] = value;
        await this.loadData();
        this.renderCurrentTabCharts();
    }

    async onResetFilters() {
        this.state.filters = {
            department_id: "",
            asset_type_id: "",
            employee_id: "",
            location: "",
            vendor_id: "",
            status: "all",
        };
        await this.loadData();
        this.renderCurrentTabCharts();
    }

    async onRefreshData() {
        await this.loadData();
        this.renderCurrentTabCharts();
    }

    switchTab(tabName) {
        this.state.active_tab = tabName;
        // Allow OWL to update the DOM before mounting ChartJS canvases
        setTimeout(() => {
            this.renderCurrentTabCharts();
        }, 50);
    }

    onTableSearch(query) {
        this.state.table_search_query = query;
    }

    filteredTableRows() {
        const rows = this.state.data.asset_summary || [];
        const query = (this.state.table_search_query || "").toLowerCase().trim();
        if (!query) {
            return rows;
        }
        return rows.filter((r) => {
            return (
                (r.name && r.name.toLowerCase().includes(query)) ||
                (r.asset_name && r.asset_name.toLowerCase().includes(query)) ||
                (r.department && r.department.toLowerCase().includes(query)) ||
                (r.employee && r.employee.toLowerCase().includes(query)) ||
                (r.vendor && r.vendor.toLowerCase().includes(query)) ||
                (r.type && r.type.toLowerCase().includes(query))
            );
        });
    }

    // ─── Formatters ───────────────────────────────────────────────────────────
    formatCurrency(amount) {
        if (!amount && amount !== 0) return "$0";
        const sym = this.state.data.currency_symbol || "$";
        const absVal = Math.abs(amount);

        if (absVal >= 1000000) {
            return `${sym}${(amount / 1000000).toFixed(2)}M`;
        } else if (absVal >= 1000) {
            return `${sym}${(amount / 1000).toFixed(1)}K`;
        }
        return `${sym}${Number(amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }

    // ─── Chart Rendering Router ───────────────────────────────────────────────
    renderCurrentTabCharts() {
        if (this.state.active_tab === "overview") {
            this.renderOverviewCharts();
        } else if (this.state.active_tab === "summary") {
            this.renderSummaryCharts();
        } else if (this.state.active_tab === "department") {
            this.renderDepartmentCharts();
        } else if (this.state.active_tab === "vendor") {
            this.renderVendorCharts();
        } else if (this.state.active_tab === "trends") {
            this.renderTrendsCharts();
        }
    }

    destroyChart(key) {
        if (this.chartInstances[key]) {
            this.chartInstances[key].destroy();
            this.chartInstances[key] = null;
        }
    }

    // ─── TAB 1: OVERVIEW CHARTS ───────────────────────────────────────────────
    renderOverviewCharts() {
        // 1. Vendor NBV
        this.destroyChart("vendorNbv");
        const canvasNbv = this.vendorNbvChartRef.el;
        if (canvasNbv && window.Chart) {
            const chartData = this.state.data.charts?.vendor_nbv || { labels: [], data: [] };
            this.chartInstances["vendorNbv"] = new window.Chart(canvasNbv, {
                type: "bar",
                data: {
                    labels: chartData.labels,
                    datasets: [
                        {
                            label: "Net Book Value (USD)",
                            data: chartData.data,
                            backgroundColor: "#7c5295",
                            hoverBackgroundColor: "#5c3c88",
                            borderRadius: 6,
                            barPercentage: 0.65,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => `NBV: ${this.formatCurrency(ctx.parsed.y)}`,
                            },
                        },
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            grid: { color: "#f1f5f9" },
                            ticks: { callback: (v) => this.formatCurrency(v) },
                        },
                        x: { grid: { display: false }, ticks: { font: { weight: "600" } } },
                    },
                },
            });
        }

        // 2. Vendor Warranty Days
        this.destroyChart("vendorWarranty");
        const canvasWarranty = this.vendorWarrantyChartRef.el;
        if (canvasWarranty && window.Chart) {
            const chartData = this.state.data.charts?.vendor_warranty || { labels: [], data: [] };
            this.chartInstances["vendorWarranty"] = new window.Chart(canvasWarranty, {
                type: "bar",
                data: {
                    labels: chartData.labels,
                    datasets: [
                        {
                            label: "Avg. Days Left",
                            data: chartData.data,
                            backgroundColor: "#4f3b78",
                            hoverBackgroundColor: "#3a285d",
                            borderRadius: 6,
                            barPercentage: 0.6,
                        },
                    ],
                },
                options: {
                    indexAxis: "y",
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => `${ctx.parsed.x} days remaining`,
                            },
                        },
                    },
                    scales: {
                        x: {
                            beginAtZero: true,
                            grid: { color: "#f1f5f9" },
                            ticks: { callback: (v) => `${v} d` },
                        },
                        y: { grid: { display: false }, ticks: { font: { weight: "600" } } },
                    },
                },
            });
        }

        // 3. Department Status
        this.destroyChart("deptStatus");
        const canvasDept = this.deptStatusChartRef.el;
        if (canvasDept && window.Chart) {
            const chartData = this.state.data.charts?.dept_status || { labels: [], datasets: [] };
            this.chartInstances["deptStatus"] = new window.Chart(canvasDept, {
                type: "bar",
                data: {
                    labels: chartData.labels,
                    datasets: chartData.datasets,
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: "bottom",
                            labels: { boxWidth: 12, font: { size: 11, weight: "600" } },
                        },
                    },
                    scales: {
                        x: { stacked: true, grid: { display: false } },
                        y: { stacked: true, beginAtZero: true, grid: { color: "#f1f5f9" }, ticks: { precision: 0 } },
                    },
                },
            });
        }

        // 4. Condition Donut
        this.destroyChart("condition");
        const canvasCond = this.conditionChartRef.el;
        if (canvasCond && window.Chart) {
            const chartData = this.state.data.charts?.condition || { labels: [], data: [], colors: [] };
            this.chartInstances["condition"] = new window.Chart(canvasCond, {
                type: "doughnut",
                data: {
                    labels: chartData.labels,
                    datasets: [
                        {
                            data: chartData.data,
                            backgroundColor: chartData.colors,
                            borderWidth: 3,
                            borderColor: "#ffffff",
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: "right",
                            labels: { boxWidth: 12, font: { size: 11, weight: "600" } },
                        },
                    },
                    cutout: "65%",
                },
            });
        }
    }

    // ─── TAB 2: ASSET SUMMARY CHARTS ──────────────────────────────────────────
    renderSummaryCharts() {
        const typeData = this.state.data.charts?.asset_type || { labels: [], counts: [], values: [] };

        // Asset Count by Type
        this.destroyChart("typeCount");
        const canvasCount = this.typeCountChartRef.el;
        if (canvasCount && window.Chart) {
            this.chartInstances["typeCount"] = new window.Chart(canvasCount, {
                type: "bar",
                data: {
                    labels: typeData.labels,
                    datasets: [
                        {
                            label: "Asset Count",
                            data: typeData.counts,
                            backgroundColor: "#6f42c1",
                            borderRadius: 6,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { beginAtZero: true, ticks: { precision: 0 } },
                        x: { grid: { display: false } },
                    },
                },
            });
        }

        // Asset Valuation by Type
        this.destroyChart("typeVal");
        const canvasVal = this.typeValChartRef.el;
        if (canvasVal && window.Chart) {
            this.chartInstances["typeVal"] = new window.Chart(canvasVal, {
                type: "bar",
                data: {
                    labels: typeData.labels,
                    datasets: [
                        {
                            label: "Purchase Cost (USD)",
                            data: typeData.values,
                            backgroundColor: "#2563eb",
                            borderRadius: 6,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => `Cost: ${this.formatCurrency(ctx.parsed.y)}`,
                            },
                        },
                    },
                    scales: {
                        y: { beginAtZero: true, ticks: { callback: (v) => this.formatCurrency(v) } },
                        x: { grid: { display: false } },
                    },
                },
            });
        }
    }

    // ─── TAB 3: DEPARTMENT ANALYSIS CHARTS ────────────────────────────────────
    renderDepartmentCharts() {
        const deptData = this.state.data.charts?.dept_analysis || { labels: [], nbv: [], cost: [], counts: [] };

        // Dept NBV
        this.destroyChart("deptNbv");
        const canvasNbv = this.deptNbvChartRef.el;
        if (canvasNbv && window.Chart) {
            this.chartInstances["deptNbv"] = new window.Chart(canvasNbv, {
                type: "bar",
                data: {
                    labels: deptData.labels,
                    datasets: [
                        {
                            label: "Net Book Value (USD)",
                            data: deptData.nbv,
                            backgroundColor: "#059669",
                            borderRadius: 6,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => `NBV: ${this.formatCurrency(ctx.parsed.y)}`,
                            },
                        },
                    },
                    scales: {
                        y: { beginAtZero: true, ticks: { callback: (v) => this.formatCurrency(v) } },
                        x: { grid: { display: false } },
                    },
                },
            });
        }

        // Dept Count
        this.destroyChart("deptCount");
        const canvasCount = this.deptCountChartRef.el;
        if (canvasCount && window.Chart) {
            this.chartInstances["deptCount"] = new window.Chart(canvasCount, {
                type: "bar",
                data: {
                    labels: deptData.labels,
                    datasets: [
                        {
                            label: "Total Assets",
                            data: deptData.counts,
                            backgroundColor: "#8b5cf6",
                            borderRadius: 6,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { beginAtZero: true, ticks: { precision: 0 } },
                        x: { grid: { display: false } },
                    },
                },
            });
        }

        // Dept Status Matrix
        this.destroyChart("deptStatusMatrix");
        const canvasMatrix = this.deptStatusMatrixChartRef.el;
        if (canvasMatrix && window.Chart) {
            const chartData = this.state.data.charts?.dept_status || { labels: [], datasets: [] };
            this.chartInstances["deptStatusMatrix"] = new window.Chart(canvasMatrix, {
                type: "bar",
                data: {
                    labels: chartData.labels,
                    datasets: chartData.datasets,
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: "top" },
                    },
                    scales: {
                        x: { stacked: true, grid: { display: false } },
                        y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } },
                    },
                },
            });
        }
    }

    // ─── TAB 4: VENDOR ANALYSIS CHARTS ────────────────────────────────────────
    renderVendorCharts() {
        const vendorNbvData = this.state.data.charts?.vendor_nbv || { labels: [], data: [] };
        const vendorWarrantyData = this.state.data.charts?.vendor_warranty || { labels: [], data: [] };
        const vendorMaintData = this.state.data.charts?.vendor_maint || { labels: [], maint: [], cost: [] };

        // Vendor NBV
        this.destroyChart("vendorAnalysisNbv");
        const canvasNbv = this.vendorAnalysisNbvChartRef.el;
        if (canvasNbv && window.Chart) {
            this.chartInstances["vendorAnalysisNbv"] = new window.Chart(canvasNbv, {
                type: "bar",
                data: {
                    labels: vendorNbvData.labels,
                    datasets: [
                        {
                            label: "Net Book Value (USD)",
                            data: vendorNbvData.data,
                            backgroundColor: "#7c5295",
                            borderRadius: 6,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => `NBV: ${this.formatCurrency(ctx.parsed.y)}`,
                            },
                        },
                    },
                    scales: {
                        y: { beginAtZero: true, ticks: { callback: (v) => this.formatCurrency(v) } },
                        x: { grid: { display: false } },
                    },
                },
            });
        }

        // Vendor Warranty Days
        this.destroyChart("vendorAnalysisWarranty");
        const canvasWarranty = this.vendorAnalysisWarrantyChartRef.el;
        if (canvasWarranty && window.Chart) {
            this.chartInstances["vendorAnalysisWarranty"] = new window.Chart(canvasWarranty, {
                type: "bar",
                data: {
                    labels: vendorWarrantyData.labels,
                    datasets: [
                        {
                            label: "Avg. Days Left",
                            data: vendorWarrantyData.data,
                            backgroundColor: "#4f3b78",
                            borderRadius: 6,
                        },
                    ],
                },
                options: {
                    indexAxis: "y",
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { beginAtZero: true, ticks: { callback: (v) => `${v} d` } },
                        y: { grid: { display: false } },
                    },
                },
            });
        }

        // Vendor Maintenance
        this.destroyChart("vendorMaint");
        const canvasMaint = this.vendorMaintChartRef.el;
        if (canvasMaint && window.Chart) {
            this.chartInstances["vendorMaint"] = new window.Chart(canvasMaint, {
                type: "bar",
                data: {
                    labels: vendorMaintData.labels,
                    datasets: [
                        {
                            label: "Maintenance Spend (USD)",
                            data: vendorMaintData.maint,
                            backgroundColor: "#ef4444",
                            borderRadius: 6,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => `Repairs: ${this.formatCurrency(ctx.parsed.y)}`,
                            },
                        },
                    },
                    scales: {
                        y: { beginAtZero: true, ticks: { callback: (v) => this.formatCurrency(v) } },
                        x: { grid: { display: false } },
                    },
                },
            });
        }
    }

    // ─── TAB 5: MONTHLY TRENDS CHARTS ─────────────────────────────────────────
    renderTrendsCharts() {
        const trendsData = this.state.data.charts?.monthly_trends || {
            labels: [],
            acquisitions: [],
            depreciation: [],
            maintenance: [],
            cum_nbv: [],
        };

        // Dual Line: Acquisitions vs Depreciation
        this.destroyChart("trendsDual");
        const canvasDual = this.trendsDualChartRef.el;
        if (canvasDual && window.Chart) {
            this.chartInstances["trendsDual"] = new window.Chart(canvasDual, {
                type: "line",
                data: {
                    labels: trendsData.labels,
                    datasets: [
                        {
                            label: "Acquisitions (USD)",
                            data: trendsData.acquisitions,
                            borderColor: "#2563eb",
                            backgroundColor: "rgba(37, 99, 235, 0.1)",
                            fill: true,
                            tension: 0.35,
                            pointRadius: 4,
                        },
                        {
                            label: "Depreciation (USD)",
                            data: trendsData.depreciation,
                            borderColor: "#d97706",
                            backgroundColor: "rgba(217, 119, 6, 0.1)",
                            fill: true,
                            tension: 0.35,
                            pointRadius: 4,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: "top" },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => `${ctx.dataset.label}: ${this.formatCurrency(ctx.parsed.y)}`,
                            },
                        },
                    },
                    scales: {
                        y: { beginAtZero: true, ticks: { callback: (v) => this.formatCurrency(v) } },
                        x: { grid: { display: false } },
                    },
                },
            });
        }

        // Area: Cumulative Net Book Value Trajectory
        this.destroyChart("trendsNbv");
        const canvasNbv = this.trendsNbvChartRef.el;
        if (canvasNbv && window.Chart) {
            this.chartInstances["trendsNbv"] = new window.Chart(canvasNbv, {
                type: "line",
                data: {
                    labels: trendsData.labels,
                    datasets: [
                        {
                            label: "Cumulative NBV (USD)",
                            data: trendsData.cum_nbv,
                            borderColor: "#059669",
                            backgroundColor: "rgba(5, 150, 105, 0.15)",
                            fill: true,
                            tension: 0.3,
                            pointRadius: 4,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => `NBV: ${this.formatCurrency(ctx.parsed.y)}`,
                            },
                        },
                    },
                    scales: {
                        y: { beginAtZero: true, ticks: { callback: (v) => this.formatCurrency(v) } },
                        x: { grid: { display: false } },
                    },
                },
            });
        }

        // Bar: Monthly Maintenance Expenses
        this.destroyChart("trendsMaint");
        const canvasMaint = this.trendsMaintChartRef.el;
        if (canvasMaint && window.Chart) {
            this.chartInstances["trendsMaint"] = new window.Chart(canvasMaint, {
                type: "bar",
                data: {
                    labels: trendsData.labels,
                    datasets: [
                        {
                            label: "Maintenance (USD)",
                            data: trendsData.maintenance,
                            backgroundColor: "#f59e0b",
                            borderRadius: 6,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => `Repairs: ${this.formatCurrency(ctx.parsed.y)}`,
                            },
                        },
                    },
                    scales: {
                        y: { beginAtZero: true, ticks: { callback: (v) => this.formatCurrency(v) } },
                        x: { grid: { display: false } },
                    },
                },
            });
        }
    }

    // ─── Click-Through Navigation Handlers ────────────────────────────────────
    onCardClick(filterType) {
        let domain = [];
        if (filterType === "active") {
            domain = [["status", "=", "assign"]];
        } else if (filterType === "confirmed") {
            domain = [["state", "=", "confirmed"]];
        }

        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Assets",
            res_model: "asset.management",
            views: [
                [false, "kanban"],
                [false, "list"],
                [false, "form"],
            ],
            domain: domain,
            target: "current",
        });
    }

    onOpenAssetRecord(assetId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Asset Details",
            res_model: "asset.management",
            res_id: assetId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    onOpenAssetList() {
        this.action.doAction("asset_management.action_assets");
    }

    onOpenDepreciationEntries() {
        this.action.doAction("asset_management.action_assets_depreciation_entry");
    }

    onOpenJournalEntries() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Journal Entries",
            res_model: "account.move",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: [["ref", "ilike", "Asset"]],
            target: "current",
        });
    }

    onCreateNewAsset() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "New Asset",
            res_model: "asset.management",
            views: [[false, "form"]],
            target: "current",
            flags: { form: { action_buttons: true } },
        });
    }

    onOpenSettings() {
        this.action.doAction("asset_management.action_assets_settings");
    }
}

registry.category("actions").add("asset_management_dashboard_tag", AssetDashboard);
