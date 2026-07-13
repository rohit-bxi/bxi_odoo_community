/** @odoo-module **/

import { Component, onMounted, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * BXI Vendor Analytics Dashboard
 * An OWL-powered analytics dashboard for the Vendor Management Portal.
 */
class VendorDashboard extends Component {
    static template = "bxi_vendor_portal.VendorDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.data = useState({
            total_vendors: 0,
            by_state: { draft: 0, pending: 0, active: 0, approved: 0, inactive: 0, blocked: 0 },
            pending_approvals: { l1: 0, l2: 0, l3: 0 },
            asn_stats: { draft: 0, confirmed: 0, dispatched: 0, delivered: 0, cancelled: 0 },
            total_asns: 0,
            categories: [],
            top_vendors: [],
            expiring_documents: 0,
            expired_documents: 0,
            avl_vendors: 0,
        });

        this.charts = {};

        onWillStart(async () => {
            await this._loadChartJs();
            await this._fetchData();
        });

        onMounted(() => {
            this._renderCharts();
            this._injectStyles();
        });
    }

    async _loadChartJs() {
        if (window.Chart) return;
        await new Promise((resolve, reject) => {
            const script = document.createElement("script");
            script.src = "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js";
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }

    async _fetchData() {
        const result = await this.orm.call("bxi.vendor", "get_vendor_dashboard_data", []);
        Object.assign(this.data, result);
    }

    _renderCharts() {
        this._destroyCharts();
        this._renderVendorStatusChart();
        this._renderAsnStatusChart();
        this._renderCategoryChart();
    }

    _destroyCharts() {
        Object.values(this.charts).forEach(c => c && c.destroy && c.destroy());
        this.charts = {};
    }

    _renderVendorStatusChart() {
        const ctx = document.getElementById("vendorStatusChart");
        if (!ctx || !window.Chart) return;
        const d = this.data.by_state;
        this.charts.status = new Chart(ctx, {
            type: "doughnut",
            data: {
                labels: ["Active", "Approved", "Pending", "Draft", "Inactive", "Blocked"],
                datasets: [{
                    data: [d.active, d.approved, d.pending, d.draft, d.inactive, d.blocked],
                    backgroundColor: ["#22c55e", "#3b82f6", "#f59e0b", "#94a3b8", "#64748b", "#ef4444"],
                    borderWidth: 3,
                    borderColor: "#1e1e2e",
                    hoverOffset: 12,
                }],
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: { color: "#cbd5e1", font: { size: 12 } },
                    },
                    tooltip: {
                        callbacks: {
                            label: ctx => ` ${ctx.label}: ${ctx.parsed} vendors`,
                        },
                    },
                },
                animation: { animateRotate: true, duration: 900 },
                cutout: "65%",
            },
        });
    }

    _renderAsnStatusChart() {
        const ctx = document.getElementById("asnStatusChart");
        if (!ctx || !window.Chart) return;
        const d = this.data.asn_stats;
        this.charts.asn = new Chart(ctx, {
            type: "bar",
            data: {
                labels: ["Draft", "Confirmed", "Dispatched", "Delivered", "Cancelled"],
                datasets: [{
                    label: "ASN Count",
                    data: [d.draft, d.confirmed, d.dispatched, d.delivered, d.cancelled],
                    backgroundColor: ["#94a3b8", "#3b82f6", "#f59e0b", "#22c55e", "#ef4444"],
                    borderRadius: 8,
                    borderWidth: 0,
                }],
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { display: false },
                },
                scales: {
                    x: {
                        ticks: { color: "#94a3b8" },
                        grid: { color: "rgba(148,163,184,0.1)" },
                    },
                    y: {
                        ticks: { color: "#94a3b8", precision: 0 },
                        grid: { color: "rgba(148,163,184,0.1)" },
                        beginAtZero: true,
                    },
                },
                animation: { duration: 900 },
            },
        });
    }

    _renderCategoryChart() {
        const ctx = document.getElementById("categoryChart");
        if (!ctx || !window.Chart) return;
        const cats = this.data.categories;
        const palette = ["#3b82f6","#8b5cf6","#06b6d4","#22c55e","#f59e0b","#f43f5e","#64748b","#ec4899"];
        this.charts.category = new Chart(ctx, {
            type: "polarArea",
            data: {
                labels: cats.map(c => c.name),
                datasets: [{
                    data: cats.map(c => c.count),
                    backgroundColor: cats.map((_, i) => palette[i % palette.length] + "bb"),
                    borderColor: cats.map((_, i) => palette[i % palette.length]),
                    borderWidth: 2,
                }],
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: { color: "#cbd5e1", font: { size: 11 } },
                    },
                },
                scales: {
                    r: {
                        ticks: { color: "#94a3b8", backdropColor: "transparent" },
                        grid: { color: "rgba(148,163,184,0.15)" },
                    },
                },
                animation: { duration: 900 },
            },
        });
    }

    openVendors({ state, pending, avl } = {}) {
        let domain = [];
        if (state) domain = [["state", "=", state]];
        else if (pending) domain = [["state", "in", ["submitted", "l1_approved", "l2_approved"]]];
        else if (avl) domain = [["is_avl", "=", true]];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Vendors",
            res_model: "bxi.vendor",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain,
        });
    }

    openAsns({ delayed } = {}) {
        const domain = delayed ? [["is_delayed", "=", true]] : [];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "ASNs",
            res_model: "bxi.vendor.asn",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain,
        });
    }

    openExpiringDocs() {
        this.action.doAction("bxi_vendor_portal.action_vendor_document_expiring");
    }

    openExpiredDocs() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Expired Documents",
            res_model: "bxi.vendor.document",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [["is_expired", "=", true]],
        });
    }

    // ── Inline CSS Injection ───────────────────────────────────────────────
    _injectStyles() {
        if (document.getElementById("vd_styles")) return;
        const style = document.createElement("style");
        style.id = "vd_styles";
        style.textContent = `
.vd_root { background:#0f0f1a; height:100%; overflow-y:auto; padding:24px; font-family:'Inter',sans-serif; color:#e2e8f0; box-sizing:border-box; }

/* ── Header ── */
.vd_header { display:flex; justify-content:space-between; align-items:center; margin-bottom:28px; }
.vd_header_left { display:flex; align-items:center; gap:16px; }
.vd_logo { font-size:48px; }
.vd_title { font-size:26px; font-weight:700; margin:0; background:linear-gradient(135deg,#3b82f6,#8b5cf6); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.vd_subtitle { margin:4px 0 0; font-size:13px; color:#64748b; }
.vd_refresh_badge { display:flex; align-items:center; gap:8px; background:rgba(34,197,94,0.12); border:1px solid rgba(34,197,94,0.3); border-radius:20px; padding:6px 14px; font-size:13px; color:#22c55e; }
.vd_dot { width:8px; height:8px; border-radius:50%; background:#22c55e; animation:pulse 2s infinite; }
@keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:.4;} }

/* ── KPI Strip ── */
.vd_kpi_strip { display:grid; grid-template-columns:repeat(8,1fr); gap:14px; margin-bottom:24px; }
@media(max-width:1600px){ .vd_kpi_strip{ grid-template-columns:repeat(4,1fr); } }
@media(max-width:1000px){ .vd_kpi_strip{ grid-template-columns:repeat(2,1fr); } }
@media(max-width:550px){ .vd_kpi_strip{ grid-template-columns:1fr; } }
.vd_kpi_card { background:rgba(30,30,46,0.9); border:1px solid rgba(255,255,255,0.07); border-radius:14px; padding:18px 14px; display:flex; align-items:center; gap:12px; cursor:pointer; transition:all .25s; }
.vd_kpi_card:hover { transform:translateY(-3px); border-color:rgba(59,130,246,0.5); box-shadow:0 8px 30px rgba(59,130,246,0.2); }
.vd_kpi_icon { font-size:30px; }
.vd_kpi_value { font-size:28px; font-weight:700; }
.vd_kpi_label { font-size:11px; color:#64748b; text-transform:uppercase; letter-spacing:.5px; margin-top:2px; }
.vd_kpi_total .vd_kpi_value { color:#3b82f6; }
.vd_kpi_active .vd_kpi_value { color:#22c55e; }
.vd_kpi_pending .vd_kpi_value { color:#f59e0b; }
.vd_kpi_avl .vd_kpi_value { color:#8b5cf6; }
.vd_kpi_blocked .vd_kpi_value { color:#ef4444; }
.vd_kpi_asn .vd_kpi_value { color:#06b6d4; }
.vd_kpi_expiry .vd_kpi_value { color:#f59e0b; }
.vd_kpi_expired .vd_kpi_value { color:#ef4444; }

/* ── Grid ── */
.vd_grid { display:grid; grid-template-columns:repeat(2,1fr); gap:20px; }
@media(max-width:1100px){ .vd_grid{ grid-template-columns:1fr; } }

/* ── Panel ── */
.vd_panel { background:rgba(30,30,46,0.9); border:1px solid rgba(255,255,255,0.07); border-radius:16px; overflow:hidden; }
.vd_panel_wide { grid-column:1 / -1; }
.vd_panel_header { padding:16px 20px; border-bottom:1px solid rgba(255,255,255,0.06); }
.vd_panel_header h3 { margin:0; font-size:15px; font-weight:600; color:#e2e8f0; }
.vd_panel_body { padding:20px; }

/* ── Approval Rows ── */
.vd_approval_row { display:flex; align-items:center; gap:12px; margin-bottom:16px; cursor:pointer; transition:opacity .2s; }
.vd_approval_row:hover { opacity:.8; }
.vd_approval_level { width:36px; height:36px; border-radius:8px; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:13px; flex-shrink:0; }
.vd_l1 { background:rgba(59,130,246,.2); color:#3b82f6; border:1px solid rgba(59,130,246,.4); }
.vd_l2 { background:rgba(139,92,246,.2); color:#8b5cf6; border:1px solid rgba(139,92,246,.4); }
.vd_l3 { background:rgba(245,158,11,.2); color:#f59e0b; border:1px solid rgba(245,158,11,.4); }
.vd_approval_label { font-size:13px; color:#94a3b8; width:160px; flex-shrink:0; }
.vd_approval_bar_wrap { flex:1; background:rgba(255,255,255,0.06); border-radius:6px; height:10px; overflow:hidden; }
.vd_approval_bar { height:100%; background:#3b82f6; border-radius:6px; transition:width .8s ease; }
.vd_bar_l2 { background:#8b5cf6; }
.vd_bar_l3 { background:#f59e0b; }
.vd_approval_count { font-size:18px; font-weight:700; width:32px; text-align:right; }

/* ── Top Vendors Table ── */
.vd_table { width:100%; border-collapse:collapse; font-size:13px; }
.vd_table th { padding:10px 14px; text-align:left; color:#64748b; font-weight:600; text-transform:uppercase; font-size:11px; letter-spacing:.5px; border-bottom:1px solid rgba(255,255,255,0.07); }
.vd_table td { padding:12px 14px; border-bottom:1px solid rgba(255,255,255,0.04); }
.vd_table tr:hover td { background:rgba(59,130,246,0.06); }
.vd_code_cell { font-family:monospace; font-size:12px; color:#64748b; }
.vd_score_bar_wrap { position:relative; background:rgba(255,255,255,0.06); border-radius:6px; height:18px; overflow:hidden; min-width:80px; }
.vd_score_bar { height:100%; border-radius:6px; transition:width .8s ease; }
.vd_score_label { position:absolute; right:6px; top:1px; font-size:11px; font-weight:600; }
.vd_grade { padding:3px 10px; border-radius:12px; font-size:11px; font-weight:700; }
.vd_grade_a { background:rgba(34,197,94,0.15); color:#22c55e; }
.vd_grade_b { background:rgba(59,130,246,0.15); color:#3b82f6; }
.vd_grade_c { background:rgba(245,158,11,0.15); color:#f59e0b; }
.vd_grade_d { background:rgba(239,68,68,0.15); color:#ef4444; }
        `;
        document.head.appendChild(style);
    }
}

registry.category("actions").add("vendor_dashboard", VendorDashboard);
